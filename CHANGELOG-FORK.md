# Changelog del fork

Cambios respecto al repo original [Reinharderino/ts6-musicbot](https://github.com/Reinharderino/ts6-musicbot).

## Reliability / correctness

- **Volumen unificado**: eliminado el filtro `-af volume=` de ffmpeg. El
  volumen ahora se aplica 100 % en el sink de PulseAudio vía `pactl`, por lo
  que `!vol` tiene efecto inmediato y persiste entre tracks.
- **Cache limpio al arrancar y al salir**: `clear_cache()` se llama en
  `main()` tanto al inicio como en el `finally`. Evita acumular archivos
  huérfanos si el bot fue matado abruptamente.
- **Parser de eventos ServerQuery robusto**: reemplazado el regex
  orden-dependiente por un tokenizador `key=value` genérico y se amplió la
  tabla de escape TS3 (`\a \b \f \n \r \t \v`). Compatible con las dos
  formas en que llega un mensaje (notifytextmessage y textmessage de log).
- **Auto-update de `yt-dlp` al arrancar** (configurable con
  `AUTO_UPDATE_YT_DLP`). YouTube rompe extractores a menudo; esto evita que
  el bot se quede desactualizado con cada build cacheada.
- **Manejo de errores por comando**: cada handler del parser está envuelto
  en try/except con reporte al canal; un error de `!play` no mata al bot.
- **Fallback a streaming si la descarga falla**: si `download_track` revienta,
  el track se encola igual y el player hace `re_resolve` y reproduce directo.

## Features nuevas

- `!pause` / `!resume` (vía SIGSTOP/SIGCONT al proceso ffmpeg).
- `!shuffle` — mezcla la cola pendiente.
- `!clear` — limpia la cola pendiente sin parar el track actual.
- `!playlist <URL>` — resuelve playlists (cap configurable via
  `MAX_PLAYLIST_ITEMS`, default 100) y las encola completas.
- `!np` ahora indica el estado de pausa.
- Formato HH:MM:SS para tracks >= 1 h.

## TrueNAS / deployment

- **Imagen corre como usuario no-root** (`musicbot`, UID/GID 1000 por defecto,
  remapeables en runtime vía `PUID`/`PGID` — TrueNAS usa 568 para el usuario
  "apps"). El entrypoint fue dividido en dos etapas: `entrypoint.sh` (root,
  hace el remap y el chown) → `bootstrap.sh` (musicbot, arranca Xvfb/Pulse/TS6).
- **Eliminado `cap_add: SYS_ADMIN` y `/dev/snd`**: el audio es 100 %
  virtual (null-sink de PulseAudio), nunca necesitaron existir.
- **Volumen persistente único `/data`**: cache y config del cliente TS6 bajo
  la misma raíz, fácil de mapear a un dataset.
- **`docker-compose.truenas.yml`** listo para pegar como Custom App en
  TrueNAS SCALE 24.10+.
- **Healthcheck real**: verifica proceso del bot + sink de Pulse + API
  WebQuery, en lugar de sólo pingear WebQuery.
- **Límites de recursos sugeridos** en el compose de TrueNAS.

## Calidad / mantenibilidad

- **LICENSE MIT** añadido (el repo original no tenía).
- **CI de GitHub Actions**: unit tests en Python 3.11 y 3.12, build del
  Dockerfile, lint con `ruff`.
- **Tests actualizados** — los antiguos de `chat_listener` aún referenciaban
  una versión file-poll-based del listener que ya no existe. Fueron
  reescritos para cubrir el parser nuevo, `!pause/!resume/!shuffle/!clear/!playlist`,
  y el recovery de errores.
- **Tests de integración live** marcados con `@pytest.mark.integration` y
  excluidos del run por defecto.
- **Logging configurable** via `LOG_LEVEL` y con silenciamiento por defecto
  de `asyncssh`, `aiohttp.access` y `urllib3`.
- `.env.example` re-escrito con comentarios explicativos para cada variable.
