# ts6-musicbot (TrueNAS-ready fork)

Bot de música para **TeamSpeak 6**. Reproduce audio de YouTube / SoundCloud /
~1000 sitios soportados por `yt-dlp` en un canal usando el cliente oficial de
TS6 corriendo headless en un contenedor.

> Fork de [Reinharderino/ts6-musicbot](https://github.com/Reinharderino/ts6-musicbot)
> con mejoras de fiabilidad, features extra y empaquetado listo para
> TrueNAS SCALE 24.10+ (Electric Eel / Fangtooth). Ver
> [`CHANGELOG-FORK.md`](./CHANGELOG-FORK.md).

---

## Cómo funciona

```
Usuario escribe !play <query>
        │
        ▼
ChatListener (SSH ServerQuery :10012)
  └─ recibe notifytextmessage en tiempo real
        │
        ▼
CommandParser → resolve()  → yt-dlp → audio en cache
        │
        ▼
AudioPlayer → ffmpeg → PulseAudio virtual sink (musicbot_sink)
        │
        ▼
TS6 Desktop Client captura musicbot_sink.monitor como micrófono
  └─ el audio sale en el canal de voz
        │
        ▼
WebQueryClient (HTTP :10081) → envía respuestas de texto al canal
```

Dos conexiones al servidor TS6:

- **WebQuery HTTP** (10081) — API REST stateless, para enviar mensajes.
- **SSH ServerQuery** (10012) — protocolo TS3-compatible para recibir eventos.

TS6 aún no tiene SDK oficial, así que el "bot" es el cliente oficial de
escritorio corriendo en `Xvfb`, y el audio se inyecta vía un null-sink de
PulseAudio. Es un workaround, pero funciona y es estable.

---

## Comandos

| Comando | Descripción |
|---|---|
| `!play <búsqueda o URL>` | Busca y encola un track |
| `!playlist <URL>` | Encola una playlist completa (máx. `MAX_PLAYLIST_ITEMS`) |
| `!skip` | Salta el track actual |
| `!stop` | Detiene la reproducción y limpia la cola |
| `!pause` / `!resume` | Pausa / reanuda el track actual |
| `!shuffle` | Mezcla la cola pendiente |
| `!clear` | Limpia la cola sin parar el track actual |
| `!queue` | Muestra los primeros 10 en cola |
| `!np` | Track actual (indica si está pausado) |
| `!vol <0-100>` | Ajusta el volumen |
| `!move <canal>` | Mueve el bot a otro canal |
| `!help` | Lista de comandos |

---

## Requisitos

- Docker + docker-compose (o TrueNAS SCALE 24.10+).
- Acceso a un servidor TeamSpeak 6.
- Archivo `teamspeak-client.tar.gz` (Linux 64-bit, **~183 MB**, no incluido).
- Un usuario ServerQuery con el permiso `b_virtualserver_notify_register`.

---

## 1. Obtener el cliente TS6

Descárgalo desde <https://teamspeak.com/en/downloads/#client> (Linux 64-bit) y
colócalo en la raíz del proyecto como `teamspeak-client.tar.gz`.

Versión testeada:

```bash
sha256sum teamspeak-client.tar.gz
# esperado: b9ba408a0b58170ce32384fc8bba56800840d694bd310050cbadd09246d4bf27
```

Otras versiones pueden funcionar, pero no está garantizado.

---

## 2. Crear el usuario ServerQuery

Conéctate como `serveradmin` por SSH al puerto 10012:

```bash
ssh serveradmin@tu-servidor.cl -p 10012
```

Crea el usuario y apúntate la password:

```
use 0
queryloginadd client_login_name=musicbot
# → client_login_password=XXXXXXXX
```

Dale permisos de Admin Server Query:

```
use 1
clientdbfind pattern=musicbot -uid
# → anota el cldbid
servergroupaddclient sgid=2 cldbid=<cldbid>
```

El `sgid=2` (Admin Server Query) otorga `b_virtualserver_notify_register`,
necesario para suscribirse a eventos de chat.

---

## 3. Configurar el entorno

```bash
cp .env.example .env
# editá .env con los datos de tu servidor
```

El API key de WebQuery se genera desde la UI admin del servidor TS6.

---

## 4. Ejecución (máquina Linux normal)

```bash
docker compose up -d --build
```

Ver logs filtrando ruido del cliente Electron:

```bash
docker compose logs -f 2>&1 | grep -Ev "chromium|dbus|gcm|registration_request"
```

---

## 5. Ejecución en TrueNAS SCALE 24.10+ (Electric Eel / Fangtooth)

> Requiere Docker habilitado (default en SCALE 24.10+, reemplaza al antiguo k3s).

### Layout recomendado

```
/mnt/<pool>/apps/ts6-musicbot/
├── build/                      # código + teamspeak-client.tar.gz + .env
└── data/                       # persistencia (cache + identidad TS6)
```

### Pasos

1. **Crea los datasets** en TrueNAS:
   - `apps/ts6-musicbot`
   - `apps/ts6-musicbot/build`
   - `apps/ts6-musicbot/data`

2. **Sube el código** a `build/`:
   - Clona este fork, o descarga un zip y expándelo en `build/`.
   - Coloca `teamspeak-client.tar.gz` en `build/`.
   - Copia `build/.env.example` a `build/.env` y completa los valores.

3. **Ajusta los paths** en `docker-compose.truenas.yml` (líneas marcadas con
   `⚠️ ajusta`) al nombre real de tu pool.

4. En TrueNAS SCALE → **Apps → Discover Apps → Custom App** →
   pega el contenido de `docker-compose.truenas.yml`. Launch.

5. Verifica con `docker logs -f ts6-musicbot`.

### Notas específicas de TrueNAS

- **PUID=568, PGID=568** es el usuario `apps` estándar; el entrypoint hace
  `chown` de `/data` para él automáticamente.
- **No se necesita `/dev/snd`** — el audio es 100 % virtual dentro del
  contenedor. Si ves `sound system not found`, es normal y esperado.
- **No se necesita `SYS_ADMIN`** — el cliente TS6 se lanza con `--no-sandbox`.
- **Recursos**: el cliente TS6 es un Electron y consume ~300-600 MB RAM. El
  compose pone un límite suave de 1 GB; ajústalo si corre con otras apps.
- **Healthcheck** revisa proceso + sink Pulse + WebQuery. Si TrueNAS muestra
  "unhealthy", mira el log del healthcheck dentro del contenedor.
- **Primer arranque** puede tardar ~1 min (pip install del requirements + pull
  de `yt-dlp` latest). `start_period: 60s` ya está considerando esto.

---

## Estructura del proyecto

```
ts6-musicbot/
├── bot/
│   ├── main.py                  # Orquestador principal (asyncio)
│   ├── healthcheck.py           # Docker healthcheck multi-check
│   ├── ts6/
│   │   ├── webquery.py          # Cliente HTTP WebQuery
│   │   └── chat_listener.py     # Cliente SSH ServerQuery + parser notify
│   ├── audio/
│   │   ├── player.py            # Cola + ffmpeg → PulseAudio + pause/resume
│   │   └── resolver.py          # yt-dlp: track + playlist + re-resolve
│   ├── commands/
│   │   └── parser.py            # Dispatcher de !comandos
│   └── tests/                   # pytest + pytest-asyncio
├── scripts/
│   ├── entrypoint.sh            # Stage 1 (root): remap PUID/PGID + chown
│   ├── bootstrap.sh             # Stage 2 (musicbot): Xvfb + Pulse + TS6 + bot
│   └── launch_ts6.sh            # Conecta el cliente TS6 al server
├── ts6_config/
│   └── settings.ini             # Config del cliente TS6
├── .github/workflows/ci.yml     # Lint + tests + docker build
├── Dockerfile
├── docker-compose.yml           # Deployment genérico
├── docker-compose.truenas.yml   # Deployment TrueNAS SCALE Custom App
└── .env.example
```

---

## Desarrollo

```bash
# Tests unitarios (rápidos, sin servidor real)
pytest

# Tests de integración (requieren .env apuntando a un servidor real)
pytest -m integration

# Lint
ruff check bot/
```

---

## Troubleshooting

**El bot no responde a comandos**
Verifica que `musicbot` tenga `b_virtualserver_notify_register`. En el log
deberías ver `ChatListener ready — waiting for messages in <canal>`.

**Access denied en PulseAudio**
Reinicia el contenedor — el entrypoint mata instancias previas de Pulse.

**Audio entrecortado**
`ffmpeg -reconnect` se recupera sólo. Si es constante, revisa el ancho de
banda del servidor TS.

**El cliente TS6 no se conecta**
Entra al contenedor (`docker exec -it ts6-musicbot bash`) y mira
`/tmp/ts6_client.log`.

**yt-dlp rompe con "Sign in to confirm you're not a bot"**
YouTube cambia sus anti-bot. El auto-update ayuda, pero a veces hace falta
`--cookies-from-browser` o cookies.txt. Roadmap.

---

## Licencia

MIT — ver [`LICENSE`](./LICENSE). Basado en el trabajo original de
[Reinharderino](https://github.com/Reinharderino/ts6-musicbot).
