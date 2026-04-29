"""
Chat command dispatcher.

Commands (channel chat only):
  !play  (!p)          Enqueue track and start playback
  !playlist <URL>      Enqueue a playlist (capped at MAX_PLAYLIST_ITEMS)
  !skip  (!s)          Skip current track
  !stop                Clear queue and stop playback
  !pause               Pause current track
  !resume              Resume paused track
  !shuffle             Shuffle pending queue
  !clear               Clear pending queue (keeps current track)
  !queue               Show queued tracks (first 10)
  !np                  Now playing
  !vol <0-100>         Set volume
  !move <channel>      Move bot to another channel
  !help                List commands
"""

import logging
import os

from audio.player import AudioPlayer
from audio.resolver import download_track, resolve, resolve_playlist
from ts6.webquery import WebQueryClient

log = logging.getLogger(__name__)

BOT_NICKNAME: str | None = None

# CHAT_VERBOSE=1 restaura los mensajes intermedios de !play:
#   "Encontrado: ..." + "Descargando: 25/50/75/100%".
# Por default (0) el bot solo anuncia "Buscando..." y la confirmacion
# final "[pos] title - pedido por sender".
_CHAT_VERBOSE = os.getenv("CHAT_VERBOSE", "0") != "0"


def _fmt_duration(seconds: int) -> str:
    seconds = int(seconds or 0)
    mins, secs = divmod(seconds, 60)
    if mins >= 60:
        h, m = divmod(mins, 60)
        return f"{h}:{m:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"


class CommandParser:
    def __init__(self, player: AudioPlayer, ts_client: WebQueryClient,
                 listener=None):
        self.player = player
        self.ts = ts_client
        self.listener = listener  # ChatListener — needed for !move

    async def handle(self, sender: str, message: str) -> None:
        if not message.startswith("!"):
            return
        if sender == BOT_NICKNAME:
            return

        parts = message.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        handlers = {
            "!play": self._cmd_play,
            "!p": self._cmd_play,           # alias corto de !play
            "!playlist": self._cmd_playlist,
            "!skip": self._cmd_skip,
            "!s": self._cmd_skip,           # alias corto de !skip
            "!stop": self._cmd_stop,
            "!pause": self._cmd_pause,
            "!resume": self._cmd_resume,
            "!shuffle": self._cmd_shuffle,
            "!clear": self._cmd_clear,
            "!queue": self._cmd_queue,
            "!np": self._cmd_np,
            "!vol": self._cmd_vol,
            "!move": self._cmd_move,
            "!netstats": self._cmd_netstats,
            "!help": self._cmd_help,
        }

        handler = handlers.get(cmd)
        if handler:
            try:
                await handler(sender, args)
            except Exception as e:
                log.exception("Handler %s failed", cmd)
                try:
                    await self.ts.send_channel_message(f"Error en {cmd}: {e}")
                except Exception:
                    pass

    # ── Playback ────────────────────────────────────────────────────────────

    async def _cmd_play(self, sender: str, args: str) -> None:
        if not args:
            await self.ts.send_channel_message("Uso: !play <busqueda o URL>")
            return
        await self.ts.send_channel_message(f"Buscando: {args}...")
        try:
            track = await resolve(args)
        except Exception as e:
            await self.ts.send_channel_message(f"No encontre nada: {e}")
            return

        dur = _fmt_duration(track["duration"])
        if _CHAT_VERBOSE:
            await self.ts.send_channel_message(
                f"Encontrado: {track['title']} ({dur}) — descargando..."
            )

        progress_cb = None
        if _CHAT_VERBOSE:
            last_sent = [0]

            async def on_progress(pct: int) -> None:
                if pct - last_sent[0] >= 25 or pct == 100:
                    last_sent[0] = pct
                    await self.ts.send_channel_message(f"Descargando: {pct}%")

            progress_cb = on_progress

        try:
            local_path = await download_track(track, progress_cb)
            track = {**track, "local_path": local_path}
        except Exception as e:
            log.warning("Download failed for %s: %s — will stream instead", track["title"], e)

        pos = await self.player.enqueue(track)
        await self.ts.send_channel_message(
            f"[{pos}] {track['title']} ({dur}) - pedido por {sender}"
        )

    async def _cmd_playlist(self, sender: str, args: str) -> None:
        if not args or not args.startswith("http"):
            await self.ts.send_channel_message("Uso: !playlist <URL>")
            return
        await self.ts.send_channel_message(f"Resolviendo playlist: {args}")
        try:
            tracks = await resolve_playlist(args)
        except Exception as e:
            await self.ts.send_channel_message(f"No pude resolver la playlist: {e}")
            return
        if not tracks:
            await self.ts.send_channel_message("La playlist esta vacia o no accesible.")
            return
        total = await self.player.enqueue_many(tracks)
        await self.ts.send_channel_message(
            f"Encoladas {len(tracks)} pistas (cola total: {total}) - pedido por {sender}"
        )

    async def _cmd_skip(self, sender: str, _: str) -> None:
        await self.player.skip()
        await self.ts.send_channel_message(f"{sender} salto el track.")

    async def _cmd_stop(self, sender: str, _: str) -> None:
        await self.player.stop()
        await self.ts.send_channel_message(f"{sender} detuvo la reproduccion.")

    async def _cmd_pause(self, sender: str, _: str) -> None:
        ok = await self.player.pause()
        if ok:
            await self.ts.send_channel_message(f"{sender} pauso la reproduccion.")
        else:
            await self.ts.send_channel_message("No hay nada que pausar.")

    async def _cmd_resume(self, sender: str, _: str) -> None:
        ok = await self.player.resume()
        if ok:
            await self.ts.send_channel_message(f"{sender} reanudo la reproduccion.")
        else:
            await self.ts.send_channel_message("No hay nada pausado.")

    async def _cmd_shuffle(self, sender: str, _: str) -> None:
        n = await self.player.shuffle()
        await self.ts.send_channel_message(f"Cola mezclada ({n} tracks).")

    async def _cmd_clear(self, sender: str, _: str) -> None:
        n = await self.player.clear_queue()
        await self.ts.send_channel_message(f"Cola limpiada ({n} tracks removidos).")

    async def _cmd_queue(self, sender: str, _: str) -> None:
        if not self.player.queue:
            await self.ts.send_channel_message("La cola esta vacia.")
            return
        lines = [f"{i+1}. {t['title']}" for i, t in enumerate(self.player.queue[:10])]
        more = ""
        if len(self.player.queue) > 10:
            more = f"\n...y {len(self.player.queue) - 10} mas"
        await self.ts.send_channel_message("Cola:\n" + "\n".join(lines) + more)

    async def _cmd_np(self, sender: str, _: str) -> None:
        track = self.player.current_track()
        if track:
            dur = _fmt_duration(track["duration"])
            state = " (pausado)" if self.player.is_paused() else ""
            await self.ts.send_channel_message(
                f"Reproduciendo{state}: {track['title']} ({dur})"
            )
        else:
            await self.ts.send_channel_message("No hay nada reproduciendose.")

    async def _cmd_vol(self, sender: str, args: str) -> None:
        try:
            vol = int(args)
        except ValueError:
            await self.ts.send_channel_message("Uso: !vol <0-100>")
            return
        await self.player.set_volume(vol)
        await self.ts.send_channel_message(f"Volumen: {self.player.volume}%")

    # ── Meta ────────────────────────────────────────────────────────────────

    async def _cmd_move(self, sender: str, args: str) -> None:
        if not args:
            await self.ts.send_channel_message("Uso: !move <canal>")
            return
        if not self.listener:
            await self.ts.send_channel_message("Move no disponible.")
            return
        await self.player.stop()
        ok = await self.listener.move_to_channel(args)
        if ok:
            await self.ts.send_channel_message(
                f"Movido a {args} por {sender}."
            )
        else:
            await self.ts.send_channel_message(f"Canal no encontrado: {args}")

    async def _cmd_netstats(self, sender: str, _: str) -> None:
        transport = getattr(self.listener, "_transport", None)
        if not self.listener or not transport:
            await self.ts.send_channel_message("Stats no disponibles.")
            return
        ssh_chan = getattr(transport, "_chan", None)
        ssh_session = getattr(transport, "_session", None)
        if not ssh_session or not ssh_chan:
            await self.ts.send_channel_message("Stats no disponibles (requiere SSH transport).")
            return
        try:
            ts_clid = await self.ts.get_own_client_id()
            resp = await ssh_session.cmd(
                ssh_chan, f"clientinfo clid={ts_clid}"
            )
            fields = {}
            for token in resp.split():
                if "=" in token:
                    k, _, v = token.partition("=")
                    fields[k] = v
            conn_fields = {k: v for k, v in fields.items() if k.startswith("connection_")}
            await self.ts.send_channel_message(str(conn_fields))
        except Exception as e:
            await self.ts.send_channel_message(f"Error obteniendo stats: {e}")

    async def _cmd_help(self, sender: str, _: str) -> None:
        await self.ts.send_channel_message(
            "Comandos: !play (!p) <q> | !playlist <url> | !skip (!s) | !stop "
            "| !pause | !resume | !shuffle | !clear | !queue | !np | !vol <n> "
            "| !move <canal> | !help"
        )
