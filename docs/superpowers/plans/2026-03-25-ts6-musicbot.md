# TS6 MusicBot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Dockerized TeamSpeak 6 music bot that listens to chat commands and plays audio via a PulseAudio virtual sink captured by the TS6 client as a microphone.

**Architecture:** Python async orchestrator (aiohttp + asyncio) communicates with TS6 WebQuery HTTP API for chat I/O; audio pipeline routes yt-dlp → ffmpeg → PulseAudio virtual sink → TS6 client microphone input; TS6 GUI client runs headless via Xvfb inside Docker.

**Tech Stack:** Python 3.12, aiohttp, yt-dlp, ffmpeg-python, pulsectl, pytest + pytest-asyncio, Docker + docker-compose, Ubuntu 24.04

---

## Notes

- **TS6 binary name:** `TeamSpeak` (confirmed from tar.gz — NOT `teamspeak6`)
- **WebQuery port:** 10081 (from `.env`) — firewall blocks external access; API only reachable from within container or server
- **tar.gz:** `teamspeak-client.tar.gz` already in project root — Dockerfile copies it directly, no download needed
- **`textmessagereceive` endpoint:** Must be tested from within the running container in Task 3
- **Project root:** `/mnt/Crucial/TSYoutubeClient` — all paths below are relative to this

---

## File Map

```
ts6-musicbot/                     ← project root (create this structure)
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── README.md
├── teamspeak-client.tar.gz       ← already exists, used by Dockerfile
├── .env                          ← already exists, NOT committed
│
├── scripts/
│   ├── entrypoint.sh
│   ├── setup_audio.sh
│   └── launch_ts6.sh
│
├── ts6_config/
│   └── settings.ini              ← pre-configured TS6 identity/bookmarks
│
└── bot/
    ├── main.py                   ← async entry point, wires all modules
    ├── requirements.txt
    ├── healthcheck.py            ← verifies WebQuery reachability
    │
    ├── ts6/
    │   ├── __init__.py
    │   ├── webquery.py           ← async HTTP client for WebQuery API
    │   └── chat_listener.py     ← polls WebQuery for new channel messages
    │
    ├── audio/
    │   ├── __init__.py
    │   ├── resolver.py           ← yt-dlp: query/URL → stream URL + metadata
    │   └── player.py             ← ffmpeg → PulseAudio sink, queue management
    │
    ├── commands/
    │   ├── __init__.py
    │   └── parser.py             ← dispatches !play/!skip/!stop/!queue/!np/!vol/!help
    │
    └── tests/
        ├── conftest.py
        ├── test_webquery.py
        ├── test_chat_listener.py
        ├── test_resolver.py
        ├── test_player.py
        └── test_parser.py
```

---

## Task 1: Project scaffold and git init

**Files:**
- Create: `bot/requirements.txt`
- Create: `bot/ts6/__init__.py`, `bot/audio/__init__.py`, `bot/commands/__init__.py`
- Create: `bot/tests/conftest.py`

- [ ] **Step 1: Initialize git repo**

```bash
cd /mnt/Crucial/TSYoutubeClient
git init
echo ".env" > .gitignore
echo "__pycache__/" >> .gitignore
echo "*.pyc" >> .gitignore
echo ".pytest_cache/" >> .gitignore
echo "audio_cache/" >> .gitignore
```

- [ ] **Step 2: Create directory structure**

```bash
mkdir -p bot/ts6 bot/audio bot/commands bot/tests scripts ts6_config docs/superpowers/plans
touch bot/ts6/__init__.py bot/audio/__init__.py bot/commands/__init__.py
```

- [ ] **Step 3: Write requirements.txt**

Create `bot/requirements.txt`:
```
aiohttp>=3.9
yt-dlp>=2024.1
ffmpeg-python>=0.2
pulsectl>=23.5
python-dotenv>=1.0
aiofiles>=23.0
pytest>=8.0
pytest-asyncio>=0.23
aioresponses>=0.7
```

- [ ] **Step 4: Write conftest.py**

Create `bot/tests/conftest.py`:
```python
import pytest
import os

# Make bot/ the import root for all tests
os.environ.setdefault("TS_WEBQUERY_HOST", "localhost")
os.environ.setdefault("TS_WEBQUERY_PORT", "10081")
os.environ.setdefault("TS_WEBQUERY_APIKEY", "test-key")
os.environ.setdefault("TS_BOT_NICKNAME", "testbot")
os.environ.setdefault("AUDIO_VOLUME", "85")
```

- [ ] **Step 5: Install deps**

```bash
cd /mnt/Crucial/TSYoutubeClient
pip install --break-system-packages -r bot/requirements.txt
```

Expected: all packages install without errors.

- [ ] **Step 6: Commit scaffold**

```bash
git add bot/ scripts/ ts6_config/ docs/ .gitignore
git commit -m "chore: project scaffold, requirements, test config"
```

---

## Task 2: WebQueryClient

**Files:**
- Create: `bot/ts6/webquery.py`
- Create: `bot/tests/test_webquery.py`

- [ ] **Step 1: Write failing tests**

Create `bot/tests/test_webquery.py`:
```python
import pytest
import pytest_asyncio
from aioresponses import aioresponses
from ts6.webquery import WebQueryClient

BASE = "http://localhost:10081"

@pytest.fixture
def client():
    return WebQueryClient()

@pytest.mark.asyncio
async def test_start_creates_session(client):
    await client.start()
    assert client.session is not None
    await client.stop()

@pytest.mark.asyncio
async def test_get_clientlist(client):
    with aioresponses() as m:
        m.get(f"{BASE}/1/clientlist", payload={"body": [{"client_nickname": "alice"}]})
        await client.start()
        result = await client.get_clients()
        await client.stop()
    assert result["body"][0]["client_nickname"] == "alice"

@pytest.mark.asyncio
async def test_send_channel_message(client):
    with aioresponses() as m:
        m.post(f"{BASE}/1/sendtextmessage", payload={"status": {"code": 0}})
        await client.start()
        await client.send_channel_message("hello")
        await client.stop()
    # No exception = success

@pytest.mark.asyncio
async def test_get_channels(client):
    with aioresponses() as m:
        m.get(f"{BASE}/1/channellist", payload={"body": [{"channel_name": "TendroAudio"}]})
        await client.start()
        result = await client.get_channels()
        await client.stop()
    assert result["body"][0]["channel_name"] == "TendroAudio"

@pytest.mark.asyncio
async def test_textmessagereceive(client):
    """Tests the textmessagereceive endpoint used by ChatListener."""
    with aioresponses() as m:
        m.get(f"{BASE}/1/textmessagereceive", payload={"body": []})
        await client.start()
        result = await client.get_text_messages()
        await client.stop()
    assert "body" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /mnt/Crucial/TSYoutubeClient/bot
python -m pytest tests/test_webquery.py -v 2>&1 | head -30
```

Expected: ImportError or AttributeError — module doesn't exist yet.

- [ ] **Step 3: Implement webquery.py**

Create `bot/ts6/webquery.py`:
```python
import aiohttp
import os


class WebQueryClient:
    def __init__(self):
        self.base_url = (
            f"http://{os.getenv('TS_WEBQUERY_HOST', 'localhost')}"
            f":{os.getenv('TS_WEBQUERY_PORT', '10081')}"
        )
        self.api_key = os.getenv("TS_WEBQUERY_APIKEY", "")
        self.vserver = "1"
        self.session: aiohttp.ClientSession | None = None

    async def start(self):
        self.session = aiohttp.ClientSession(
            headers={"X-API-Key": self.api_key}
        )

    async def stop(self):
        if self.session:
            await self.session.close()
            self.session = None

    async def get(self, endpoint: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}/{self.vserver}/{endpoint}"
        async with self.session.get(url, params=params) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def post(self, endpoint: str, data: dict | None = None) -> dict:
        url = f"{self.base_url}/{self.vserver}/{endpoint}"
        async with self.session.post(url, json=data) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def send_channel_message(self, message: str) -> None:
        await self.post("sendtextmessage", {"targetmode": 2, "msg": message})

    async def get_clients(self) -> dict:
        return await self.get("clientlist")

    async def get_channels(self) -> dict:
        return await self.get("channellist")

    async def get_text_messages(self) -> dict:
        """Polls for pending text messages. Returns list or empty body on no new messages."""
        return await self.get("textmessagereceive")

    async def move_client(self, client_id: int, channel_id: int) -> dict:
        return await self.post("clientmove", {"clid": client_id, "cid": channel_id})

    async def get_channel_info(self, channel_id: int) -> dict:
        return await self.get("channelinfo", {"cid": channel_id})
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd /mnt/Crucial/TSYoutubeClient/bot
python -m pytest tests/test_webquery.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /mnt/Crucial/TSYoutubeClient
git add bot/ts6/webquery.py bot/tests/test_webquery.py
git commit -m "feat: WebQueryClient with async HTTP, all endpoints"
```

---

## Task 3: ChatListener

**Files:**
- Create: `bot/ts6/chat_listener.py`
- Create: `bot/tests/test_chat_listener.py`

**Strategy:** Use `GET /1/textmessagereceive` as Plan A. The TS6 WebQuery API implements this endpoint — it returns pending messages consumed since last call (stateful server-side buffer, similar to TS3 ServerQuery). If it returns 404/error at runtime, fall back to polling clientlist changes (Plan B). The plan is coded for Plan A; Plan B is documented as an inline comment.

- [ ] **Step 1: Write failing tests**

Create `bot/tests/test_chat_listener.py`:
```python
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from ts6.chat_listener import ChatListener


def make_client(responses):
    """Returns a mock WebQueryClient that yields responses in sequence."""
    client = MagicMock()
    client.get_text_messages = AsyncMock(side_effect=responses)
    return client


@pytest.mark.asyncio
async def test_calls_callback_on_new_message():
    messages = [
        {"body": [{"msg": "!play test", "invokerid": 5, "invokername": "alice"}]},
        {"body": []},
    ]
    client = make_client(messages + [asyncio.CancelledError()])
    received = []

    async def callback(sender, text):
        received.append((sender, text))

    listener = ChatListener(client, callback, poll_interval=0)
    try:
        await listener.start()
    except asyncio.CancelledError:
        pass

    assert received == [("alice", "!play test")]


@pytest.mark.asyncio
async def test_empty_body_key_handled():
    """API returns {"body": []} when no messages — must not crash."""
    messages = [{"body": []}, asyncio.CancelledError()]
    client = make_client(messages)
    listener = ChatListener(client, AsyncMock(), poll_interval=0)
    try:
        await listener.start()
    except asyncio.CancelledError:
        pass  # clean exit


@pytest.mark.asyncio
async def test_stop_terminates_loop():
    client = make_client([{"body": []}] * 100)
    listener = ChatListener(client, AsyncMock(), poll_interval=0)
    task = asyncio.create_task(listener.start())
    await asyncio.sleep(0)
    await listener.stop()
    await asyncio.wait_for(task, timeout=1.0)


@pytest.mark.asyncio
async def test_error_in_poll_does_not_crash():
    """Network errors are logged and polling continues."""
    messages = [Exception("network error"), {"body": []}, asyncio.CancelledError()]
    client = make_client(messages)
    listener = ChatListener(client, AsyncMock(), poll_interval=0)
    try:
        await listener.start()
    except asyncio.CancelledError:
        pass
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /mnt/Crucial/TSYoutubeClient/bot
python -m pytest tests/test_chat_listener.py -v 2>&1 | head -20
```

Expected: ImportError.

- [ ] **Step 3: Implement chat_listener.py**

Create `bot/ts6/chat_listener.py`:
```python
"""
Polls GET /1/textmessagereceive for new channel messages.

TS6 WebQuery maintains a server-side message buffer per API session.
Each call consumes pending messages (like TS3 ServerQuery events).
Returns {"body": [...]} where each item has: msg, invokerid, invokername, targetmode.

PLAN B (if textmessagereceive returns 404 at runtime):
  - Poll clientlist every POLL_INTERVAL seconds
  - Detect new clients joining and send welcome; can't receive chat via clientlist
  - Real fallback: parse server log file mounted as Docker volume
"""

import asyncio
import logging
from ts6.webquery import WebQueryClient

log = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL = 1.5


class ChatListener:
    def __init__(self, client: WebQueryClient, on_message_callback, poll_interval: float = DEFAULT_POLL_INTERVAL):
        self.client = client
        self.on_message = on_message_callback
        self.poll_interval = poll_interval
        self._running = False

    async def start(self):
        self._running = True
        log.info("ChatListener started (polling every %.1fs)", self.poll_interval)
        while self._running:
            try:
                await self._poll()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("Poll error: %s", e)
            await asyncio.sleep(self.poll_interval)

    async def stop(self):
        self._running = False

    async def _poll(self):
        response = await self.client.get_text_messages()
        messages = response.get("body", [])
        if not isinstance(messages, list):
            return
        for msg in messages:
            sender = msg.get("invokername", "unknown")
            text = msg.get("msg", "")
            if text:
                await self.on_message(sender, text)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd /mnt/Crucial/TSYoutubeClient/bot
python -m pytest tests/test_chat_listener.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /mnt/Crucial/TSYoutubeClient
git add bot/ts6/chat_listener.py bot/tests/test_chat_listener.py
git commit -m "feat: ChatListener polling textmessagereceive endpoint"
```

---

## Task 4: AudioResolver

**Files:**
- Create: `bot/audio/resolver.py`
- Create: `bot/tests/test_resolver.py`

- [ ] **Step 1: Write failing tests**

Create `bot/tests/test_resolver.py`:
```python
import pytest
from unittest.mock import patch, MagicMock
from audio.resolver import resolve


FAKE_INFO = {
    "url": "https://example.com/stream.m4a",
    "title": "Never Gonna Give You Up",
    "duration": 213,
    "webpage_url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
    "uploader": "Rick Astley",
}


@pytest.mark.asyncio
async def test_resolve_url_returns_track():
    with patch("audio.resolver._resolve_sync", return_value=FAKE_INFO):
        track = await resolve("https://youtube.com/watch?v=dQw4w9WgXcQ")
    assert track["title"] == "Never Gonna Give You Up"
    assert track["url"] == "https://example.com/stream.m4a"
    assert track["duration"] == 213


@pytest.mark.asyncio
async def test_resolve_search_query_prefixes_ytsearch():
    captured = {}

    def fake_sync(query):
        captured["query"] = query
        return FAKE_INFO

    with patch("audio.resolver._resolve_sync", side_effect=fake_sync):
        await resolve("rick astley")

    assert captured["query"].startswith("ytsearch1:")
    assert "rick astley" in captured["query"]


@pytest.mark.asyncio
async def test_resolve_raises_on_no_result():
    def fail(_):
        raise ValueError("No results found")

    with patch("audio.resolver._resolve_sync", side_effect=fail):
        with pytest.raises(ValueError):
            await resolve("xyzzy not a real song 12345")


@pytest.mark.asyncio
async def test_resolve_handles_playlist_entry():
    info_with_entries = {
        "entries": [FAKE_INFO],
        "webpage_url": "https://youtube.com/playlist?list=xxx",
    }

    def fake_sync(_):
        return info_with_entries

    with patch("audio.resolver._resolve_sync", side_effect=fake_sync):
        track = await resolve("https://youtube.com/playlist?list=xxx")

    assert track["title"] == "Never Gonna Give You Up"
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /mnt/Crucial/TSYoutubeClient/bot
python -m pytest tests/test_resolver.py -v 2>&1 | head -20
```

Expected: ImportError.

- [ ] **Step 3: Implement resolver.py**

Create `bot/audio/resolver.py`:
```python
"""
Resolves a search query or URL to a streamable audio URL via yt-dlp.
Supports YouTube, SoundCloud, and any site yt-dlp handles (~1000+).
"""

import asyncio
import yt_dlp

YDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "extract_flat": False,
}


async def resolve(query: str) -> dict:
    """
    Resolves a search query or URL to track metadata.
    Returns dict with: url, title, duration, webpage_url, uploader.
    Raises ValueError if nothing found.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _resolve_sync, query)


def _resolve_sync(query: str) -> dict:
    search_query = query if query.startswith("http") else f"ytsearch1:{query}"
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        info = ydl.extract_info(search_query, download=False)
        if info is None:
            raise ValueError(f"No results for: {query}")
        if "entries" in info:
            info = info["entries"][0]
        return {
            "url": info["url"],
            "title": info.get("title", "Untitled"),
            "duration": info.get("duration", 0),
            "webpage_url": info.get("webpage_url", query),
            "uploader": info.get("uploader", ""),
        }
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd /mnt/Crucial/TSYoutubeClient/bot
python -m pytest tests/test_resolver.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /mnt/Crucial/TSYoutubeClient
git add bot/audio/resolver.py bot/tests/test_resolver.py
git commit -m "feat: AudioResolver with yt-dlp, URL and search support"
```

---

## Task 5: AudioPlayer

**Files:**
- Create: `bot/audio/player.py`
- Create: `bot/tests/test_player.py`

- [ ] **Step 1: Write failing tests**

Create `bot/tests/test_player.py`:
```python
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from audio.player import AudioPlayer

TRACK = {"title": "Test Track", "url": "https://example.com/stream.m4a", "duration": 60}


@pytest.fixture
def player():
    return AudioPlayer()


@pytest.mark.asyncio
async def test_enqueue_returns_position(player):
    with patch.object(player, "_play_loop", new_callable=AsyncMock):
        pos = await player.enqueue(TRACK)
    assert pos == 1


@pytest.mark.asyncio
async def test_enqueue_multiple_tracks(player):
    with patch.object(player, "_play_loop", new_callable=AsyncMock):
        p1 = await player.enqueue(TRACK)
        p2 = await player.enqueue({**TRACK, "title": "Track 2"})
    assert p1 == 1
    assert p2 == 2


@pytest.mark.asyncio
async def test_stop_clears_queue(player):
    with patch.object(player, "_play_loop", new_callable=AsyncMock):
        await player.enqueue(TRACK)
        await player.enqueue(TRACK)
    mock_proc = MagicMock()
    player._current_process = mock_proc
    await player.stop()
    assert player.queue == []
    mock_proc.terminate.assert_called_once()


@pytest.mark.asyncio
async def test_skip_terminates_current(player):
    mock_proc = MagicMock()
    player._current_process = mock_proc
    await player.skip()
    mock_proc.terminate.assert_called_once()


@pytest.mark.asyncio
async def test_set_volume_clamps(player):
    with patch("audio.player.os") as mock_os:
        await player.set_volume(150)
        assert player.volume == 100
        await player.set_volume(-10)
        assert player.volume == 0


@pytest.mark.asyncio
async def test_play_loop_consumes_queue(player):
    finished = asyncio.Event()

    async def fake_play_track(track):
        pass

    player.queue = [TRACK, {**TRACK, "title": "Track 2"}]
    with patch.object(player, "_play_track", side_effect=fake_play_track):
        await player._play_loop()

    assert player.queue == []
    assert player._playing is False
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /mnt/Crucial/TSYoutubeClient/bot
python -m pytest tests/test_player.py -v 2>&1 | head -20
```

Expected: ImportError.

- [ ] **Step 3: Implement player.py**

Create `bot/audio/player.py`:
```python
"""
AudioPlayer: queue management + FFmpeg → PulseAudio virtual sink.

FFmpeg streams audio to the `musicbot_sink` PulseAudio sink.
The TS6 client captures `musicbot_sink.monitor` as its microphone input.
"""

import asyncio
import subprocess
import logging
import os

log = logging.getLogger(__name__)

PULSE_SINK = "musicbot_sink"


class AudioPlayer:
    def __init__(self):
        self.queue: list[dict] = []
        self._current_process: subprocess.Popen | None = None
        self._playing = False
        self.volume = int(os.getenv("AUDIO_VOLUME", "85"))

    async def enqueue(self, track: dict) -> int:
        """Add track to queue. Returns queue position (1-indexed). Starts playback if idle."""
        self.queue.append(track)
        if not self._playing:
            asyncio.create_task(self._play_loop())
        return len(self.queue)

    async def skip(self) -> None:
        if self._current_process:
            self._current_process.terminate()
            log.info("Skipped current track.")

    async def stop(self) -> None:
        self.queue.clear()
        if self._current_process:
            self._current_process.terminate()
        self._playing = False

    async def set_volume(self, vol: int) -> None:
        self.volume = max(0, min(100, vol))
        os.system(f"pactl set-sink-volume {PULSE_SINK} {self.volume}%")

    def current_track(self) -> dict | None:
        return self._current_track if hasattr(self, "_current_track") else None

    async def _play_loop(self) -> None:
        self._playing = True
        while self.queue:
            track = self.queue.pop(0)
            self._current_track = track
            await self._play_track(track)
        self._current_track = None
        self._playing = False

    async def _play_track(self, track: dict) -> None:
        log.info("Playing: %s", track["title"])
        cmd = [
            "ffmpeg",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-i", track["url"],
            "-acodec", "pcm_s16le",
            "-ar", "48000",
            "-ac", "2",
            "-af", f"volume={self.volume / 100}",
            "-f", "pulse",
            PULSE_SINK,
            "-loglevel", "warning",
        ]
        loop = asyncio.get_event_loop()
        self._current_process = await loop.run_in_executor(
            None, lambda: subprocess.Popen(cmd)
        )
        await loop.run_in_executor(None, self._current_process.wait)
        self._current_process = None
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd /mnt/Crucial/TSYoutubeClient/bot
python -m pytest tests/test_player.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd /mnt/Crucial/TSYoutubeClient
git add bot/audio/player.py bot/tests/test_player.py
git commit -m "feat: AudioPlayer with queue, skip, stop, volume via FFmpeg+PulseAudio"
```

---

## Task 6: CommandParser

**Files:**
- Create: `bot/commands/parser.py`
- Create: `bot/tests/test_parser.py`

- [ ] **Step 1: Write failing tests**

Create `bot/tests/test_parser.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from commands.parser import CommandParser
import commands.parser as parser_module

TRACK = {"title": "Never Gonna Give You Up", "url": "x", "duration": 213, "uploader": "Rick Astley", "webpage_url": "x"}


@pytest.fixture
def setup():
    parser_module.BOT_NICKNAME = "testbot"
    player = MagicMock()
    player.enqueue = AsyncMock(return_value=1)
    player.skip = AsyncMock()
    player.stop = AsyncMock()
    player.set_volume = AsyncMock()
    player.queue = []
    player.current_track = MagicMock(return_value=None)
    ts = MagicMock()
    ts.send_channel_message = AsyncMock()
    return CommandParser(player, ts), player, ts


@pytest.mark.asyncio
async def test_non_command_ignored(setup):
    parser, player, ts = setup
    await parser.handle("alice", "hello world")
    ts.send_channel_message.assert_not_called()


@pytest.mark.asyncio
async def test_bot_message_ignored(setup):
    parser, player, ts = setup
    await parser.handle("testbot", "!play something")
    player.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_play_resolves_and_enqueues(setup):
    parser, player, ts = setup
    with patch("commands.parser.resolve", AsyncMock(return_value=TRACK)):
        await parser.handle("alice", "!play rick astley")
    player.enqueue.assert_awaited_once()
    assert ts.send_channel_message.call_count >= 1


@pytest.mark.asyncio
async def test_play_without_args_sends_error(setup):
    parser, player, ts = setup
    await parser.handle("alice", "!play")
    ts.send_channel_message.assert_awaited_once()
    assert "Uso" in ts.send_channel_message.call_args[0][0]


@pytest.mark.asyncio
async def test_skip_delegates(setup):
    parser, player, ts = setup
    await parser.handle("alice", "!skip")
    player.skip.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_delegates(setup):
    parser, player, ts = setup
    await parser.handle("alice", "!stop")
    player.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_vol_valid(setup):
    parser, player, ts = setup
    await parser.handle("alice", "!vol 70")
    player.set_volume.assert_awaited_once_with(70)


@pytest.mark.asyncio
async def test_vol_invalid(setup):
    parser, player, ts = setup
    await parser.handle("alice", "!vol abc")
    ts.send_channel_message.assert_awaited_once()
    assert "Uso" in ts.send_channel_message.call_args[0][0]


@pytest.mark.asyncio
async def test_help_sends_message(setup):
    parser, player, ts = setup
    await parser.handle("alice", "!help")
    ts.send_channel_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_queue_empty(setup):
    parser, player, ts = setup
    await parser.handle("alice", "!queue")
    msg = ts.send_channel_message.call_args[0][0]
    assert "vac" in msg.lower() or "empty" in msg.lower()
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /mnt/Crucial/TSYoutubeClient/bot
python -m pytest tests/test_parser.py -v 2>&1 | head -20
```

Expected: ImportError.

- [ ] **Step 3: Implement parser.py**

Create `bot/commands/parser.py`:
```python
"""
Chat command dispatcher.

Commands (channel chat only):
  !play <query|URL>   Enqueue track and start playback
  !skip               Skip current track
  !stop               Clear queue and stop playback
  !queue              Show queued tracks (first 10)
  !np                 Now playing
  !vol <0-100>        Set volume
  !help               List commands
"""

import logging
from audio.player import AudioPlayer
from audio.resolver import resolve
from ts6.webquery import WebQueryClient

log = logging.getLogger(__name__)

BOT_NICKNAME: str | None = None


class CommandParser:
    def __init__(self, player: AudioPlayer, ts_client: WebQueryClient):
        self.player = player
        self.ts = ts_client

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
            "!skip": self._cmd_skip,
            "!stop": self._cmd_stop,
            "!queue": self._cmd_queue,
            "!np": self._cmd_np,
            "!vol": self._cmd_vol,
            "!help": self._cmd_help,
        }

        handler = handlers.get(cmd)
        if handler:
            await handler(sender, args)

    async def _cmd_play(self, sender: str, args: str) -> None:
        if not args:
            await self.ts.send_channel_message("Uso: !play <busqueda o URL>")
            return
        await self.ts.send_channel_message(f"Buscando: {args}...")
        try:
            track = await resolve(args)
            pos = await self.player.enqueue(track)
            mins, secs = divmod(track["duration"], 60)
            await self.ts.send_channel_message(
                f"[{pos}] {track['title']} ({mins}:{secs:02d}) - pedido por {sender}"
            )
        except Exception as e:
            await self.ts.send_channel_message(f"No encontre nada: {e}")

    async def _cmd_skip(self, sender: str, _: str) -> None:
        await self.player.skip()
        await self.ts.send_channel_message(f"{sender} salto el track.")

    async def _cmd_stop(self, sender: str, _: str) -> None:
        await self.player.stop()
        await self.ts.send_channel_message(f"{sender} detuvo la reproduccion.")

    async def _cmd_queue(self, sender: str, _: str) -> None:
        if not self.player.queue:
            await self.ts.send_channel_message("La cola esta vacia.")
            return
        lines = [f"{i+1}. {t['title']}" for i, t in enumerate(self.player.queue[:10])]
        await self.ts.send_channel_message("Cola:\n" + "\n".join(lines))

    async def _cmd_np(self, sender: str, _: str) -> None:
        track = self.player.current_track()
        if track:
            mins, secs = divmod(track["duration"], 60)
            await self.ts.send_channel_message(
                f"Reproduciendo: {track['title']} ({mins}:{secs:02d})"
            )
        else:
            await self.ts.send_channel_message("No hay nada reproduciendose.")

    async def _cmd_vol(self, sender: str, args: str) -> None:
        try:
            vol = int(args)
            await self.player.set_volume(vol)
            await self.ts.send_channel_message(f"Volumen: {vol}%")
        except ValueError:
            await self.ts.send_channel_message("Uso: !vol <0-100>")

    async def _cmd_help(self, sender: str, _: str) -> None:
        await self.ts.send_channel_message(
            "Comandos: !play <query> | !skip | !stop | !queue | !np | !vol <n> | !help"
        )
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd /mnt/Crucial/TSYoutubeClient/bot
python -m pytest tests/test_parser.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Run all tests**

```bash
cd /mnt/Crucial/TSYoutubeClient/bot
python -m pytest tests/ -v
```

Expected: all 25 tests pass.

- [ ] **Step 6: Commit**

```bash
cd /mnt/Crucial/TSYoutubeClient
git add bot/commands/parser.py bot/tests/test_parser.py
git commit -m "feat: CommandParser for !play/!skip/!stop/!queue/!np/!vol/!help"
```

---

## Task 7: main.py and healthcheck.py

**Files:**
- Create: `bot/main.py`
- Create: `bot/healthcheck.py`

- [ ] **Step 1: Write main.py**

Create `bot/main.py`:
```python
"""
Orchestrator entry point. Wires all modules and runs the async event loop.
"""

import asyncio
import logging
import os
from dotenv import load_dotenv

from ts6.webquery import WebQueryClient
from ts6.chat_listener import ChatListener
from audio.player import AudioPlayer
from commands.parser import CommandParser
import commands.parser as parser_module

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
log = logging.getLogger("main")


async def main():
    parser_module.BOT_NICKNAME = os.getenv("TS_BOT_NICKNAME", "MusicBot")

    ts_client = WebQueryClient()
    await ts_client.start()

    player = AudioPlayer()
    cmd_parser = CommandParser(player, ts_client)

    async def on_message(sender: str, message: str):
        await cmd_parser.handle(sender, message)

    listener = ChatListener(ts_client, on_message)

    log.info("Bot started. Channel: %s", os.getenv("TS_CHANNEL"))
    try:
        await ts_client.send_channel_message(
            "MusicBot connected. Type !help for commands."
        )
    except Exception as e:
        log.warning("Could not send startup message: %s", e)

    try:
        await listener.start()
    except asyncio.CancelledError:
        log.info("Shutting down...")
    finally:
        await ts_client.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Write healthcheck.py**

Create `bot/healthcheck.py`:
```python
"""
Exit 0 if WebQuery API is reachable and responds; exit 1 otherwise.
Used by Docker healthcheck.
"""

import asyncio
import sys
import os
from dotenv import load_dotenv

load_dotenv()


async def check():
    import aiohttp
    host = os.getenv("TS_WEBQUERY_HOST", "localhost")
    port = os.getenv("TS_WEBQUERY_PORT", "10081")
    key = os.getenv("TS_WEBQUERY_APIKEY", "")
    url = f"http://{host}:{port}/1/clientlist"
    try:
        async with aiohttp.ClientSession(headers={"X-API-Key": key}) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    print(f"OK: {resp.status}")
                    sys.exit(0)
                else:
                    print(f"FAIL: HTTP {resp.status} (check API key or server)")
                    sys.exit(1)
    except Exception as e:
        print(f"FAIL: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(check())
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/Crucial/TSYoutubeClient
git add bot/main.py bot/healthcheck.py
git commit -m "feat: main.py orchestrator and healthcheck"
```

---

## Task 8: Shell scripts

**Files:**
- Create: `scripts/entrypoint.sh`
- Create: `scripts/setup_audio.sh`
- Create: `scripts/launch_ts6.sh`

- [ ] **Step 1: Write entrypoint.sh**

Create `scripts/entrypoint.sh`:
```bash
#!/bin/bash
set -e

echo "[entrypoint] Starting Xvfb on :99..."
Xvfb :99 -screen 0 1280x720x24 &
XVFB_PID=$!
sleep 1

echo "[entrypoint] Starting PulseAudio..."
pulseaudio --start --log-target=stderr --exit-idle-time=-1
sleep 1

echo "[entrypoint] Setting up virtual audio..."
/app/scripts/setup_audio.sh

echo "[entrypoint] Launching TS6 client..."
/app/scripts/launch_ts6.sh &
TS6_PID=$!
sleep 8  # allow client to connect and register with WebQuery

echo "[entrypoint] Starting Python orchestrator..."
cd /app
python3 bot/main.py

# Cleanup
kill $XVFB_PID $TS6_PID 2>/dev/null || true
```

- [ ] **Step 2: Write setup_audio.sh**

Create `scripts/setup_audio.sh`:
```bash
#!/bin/bash
set -e

SINK_NAME="musicbot_sink"

# Null sink: audio is rendered here (no physical output)
pactl load-module module-null-sink \
    sink_name="$SINK_NAME" \
    sink_properties=device.description="MusicBot_Virtual_Sink"

# Expose sink monitor as a source (microphone) for the TS6 client
pactl load-module module-virtual-source \
    source_name="$SINK_NAME.mic" \
    master="$SINK_NAME.monitor"

echo "[audio] Virtual sink '$SINK_NAME' ready."
```

- [ ] **Step 3: Write launch_ts6.sh**

Create `scripts/launch_ts6.sh`:
```bash
#!/bin/bash
# Launches the TS6 client headless and connects to the configured server.
# Binary name confirmed: TeamSpeak (from teamspeak-client.tar.gz)

TS6_BIN="/opt/ts6/TeamSpeak"

if [ ! -f "$TS6_BIN" ]; then
    echo "[ts6] ERROR: TeamSpeak binary not found at $TS6_BIN"
    exit 1
fi

# ts6server:// URI — same scheme as TS3
CONNECT_URI="ts6server://${TS_SERVER_HOST}?port=${TS_SERVER_PORT:-9988}&nickname=${TS_BOT_NICKNAME:-tendroaudio}${TS_CHANNEL:+&channel=$TS_CHANNEL}${TS_SERVER_PASSWORD:+&password=$TS_SERVER_PASSWORD}"

echo "[ts6] Connecting to: $CONNECT_URI"

DISPLAY=:99 PULSE_SINK=musicbot_sink "$TS6_BIN" "$CONNECT_URI" &

# If URI argument is not honored by the client, use xdotool fallback:
# xdotool search --sync --name "TeamSpeak" key ctrl+s
# (see docs/workarounds.md)
```

- [ ] **Step 4: Make scripts executable**

```bash
chmod +x /mnt/Crucial/TSYoutubeClient/scripts/*.sh
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/Crucial/TSYoutubeClient
git add scripts/
git commit -m "feat: entrypoint, audio setup, TS6 launch scripts"
```

---

## Task 9: ts6_config/settings.ini

**Files:**
- Create: `ts6_config/settings.ini`

The TS6 client reads its config from `~/.config/TeamSpeak/`. Pre-populate it so the client auto-connects and uses the virtual microphone. The exact key names depend on the TS6 version — this is a best-effort template.

- [ ] **Step 1: Write settings.ini**

Create `ts6_config/settings.ini`:
```ini
[General]
# Pre-configured identity for the bot — overridden by TS_IDENTITY_KEY env var if set
nickname=tendroaudio

[AudioCapture]
# Use the PulseAudio virtual source created by setup_audio.sh
device=musicbot_sink.mic
enabled=true

[AudioPlayback]
# Route playback to the null sink so it doesn't echo
device=musicbot_sink
enabled=true

[Connectivity]
# Auto-accept server certificates to avoid blocking UI dialogs
acceptAllCerts=true
```

- [ ] **Step 2: Commit**

```bash
cd /mnt/Crucial/TSYoutubeClient
git add ts6_config/
git commit -m "feat: TS6 client pre-config (audio device, auto-accept certs)"
```

---

## Task 10: Dockerfile

**Files:**
- Create: `Dockerfile`

Key facts for this Dockerfile:
- TS6 binary is `TeamSpeak`, located at root of the tar.gz
- tar.gz is already in the project root — COPY it in, no download needed
- Ubuntu 24.04 base
- CEF-based app (libcef.so): needs `--no-sandbox` or `chrome-sandbox` setuid

- [ ] **Step 1: Write Dockerfile**

Create `Dockerfile`:
```dockerfile
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99
ENV PULSE_SERVER=unix:/tmp/pulse/native

RUN apt-get update && apt-get install -y \
    pulseaudio \
    pulseaudio-utils \
    xvfb \
    x11-utils \
    xdotool \
    ffmpeg \
    python3 \
    python3-pip \
    python3-venv \
    wget \
    curl \
    ca-certificates \
    jq \
    libglib2.0-0 \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2t64 \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp (latest from GitHub, more up to date than pip)
RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
    -o /usr/local/bin/yt-dlp && chmod +x /usr/local/bin/yt-dlp

# TeamSpeak 6 client from local tar.gz
COPY teamspeak-client.tar.gz /tmp/ts6client.tar.gz
RUN mkdir -p /opt/ts6 \
    && tar -xzf /tmp/ts6client.tar.gz -C /opt/ts6 \
    && rm /tmp/ts6client.tar.gz \
    && chmod +x /opt/ts6/TeamSpeak \
    && chown root:root /opt/ts6/chrome-sandbox \
    && chmod 4755 /opt/ts6/chrome-sandbox

# Pre-configure TS6 client
RUN mkdir -p /root/.config/TeamSpeak
COPY ts6_config/settings.ini /root/.config/TeamSpeak/settings.ini

WORKDIR /app

COPY bot/requirements.txt .
RUN pip3 install --break-system-packages -r requirements.txt

COPY bot/ ./bot/
COPY scripts/ ./scripts/
RUN chmod +x scripts/*.sh

CMD ["./scripts/entrypoint.sh"]
```

- [ ] **Step 2: Verify Dockerfile syntax (dry run)**

```bash
cd /mnt/Crucial/TSYoutubeClient
docker build --no-cache --dry-run . 2>&1 | head -20
```

If `--dry-run` not supported, use:
```bash
docker build -f Dockerfile --target base . 2>&1 | head -5 || true
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/Crucial/TSYoutubeClient
git add Dockerfile
git commit -m "feat: Dockerfile with TS6 client, PulseAudio, Python bot"
```

---

## Task 11: docker-compose.yml and .env.example

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`

- [ ] **Step 1: Write docker-compose.yml**

Create `docker-compose.yml`:
```yaml
version: "3.9"

services:
  ts6-musicbot:
    build: .
    container_name: ts6-musicbot
    restart: unless-stopped

    env_file: .env

    environment:
      - DISPLAY=:99

    volumes:
      - ts6_identity:/root/.config/TeamSpeak
      - audio_cache:/tmp/audio_cache

    devices:
      - /dev/snd:/dev/snd

    cap_add:
      - SYS_ADMIN

    healthcheck:
      test: ["CMD", "python3", "bot/healthcheck.py"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s

volumes:
  ts6_identity:
  audio_cache:
```

- [ ] **Step 2: Write .env.example**

Create `.env.example`:
```env
TS_SERVER_HOST=ts.tendrolapio.cl
TS_SERVER_PORT=9988
TS_SERVER_PASSWORD=
TS_CHANNEL=TendroAudio
TS_BOT_NICKNAME=tendroaudio
TS_WEBQUERY_HOST=ts.tendrolapio.cl
TS_WEBQUERY_PORT=10081
TS_WEBQUERY_APIKEY=
AUDIO_VOLUME=85
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/Crucial/TSYoutubeClient
git add docker-compose.yml .env.example
git commit -m "feat: docker-compose and .env.example"
```

---

## Task 12: Full build test

- [ ] **Step 1: Run all unit tests one final time**

```bash
cd /mnt/Crucial/TSYoutubeClient/bot
python -m pytest tests/ -v --tb=short
```

Expected: all tests pass (no failures).

- [ ] **Step 2: Build Docker image**

```bash
cd /mnt/Crucial/TSYoutubeClient
docker build -t ts6-musicbot:dev . 2>&1 | tail -20
```

Expected: `Successfully built <id>` — no errors.

- [ ] **Step 3: Verify entrypoint exists in image**

```bash
docker run --rm --entrypoint ls ts6-musicbot:dev /app/scripts/
```

Expected: `entrypoint.sh  launch_ts6.sh  setup_audio.sh`

- [ ] **Step 4: Verify TeamSpeak binary exists**

```bash
docker run --rm --entrypoint ls ts6-musicbot:dev /opt/ts6/
```

Expected: `TeamSpeak` in the listing.

- [ ] **Step 5: Final commit**

```bash
cd /mnt/Crucial/TSYoutubeClient
git add -A
git status  # verify .env is NOT staged
git commit -m "chore: verified full build — all tests pass, image builds"
```

---

## Known Issues / Runtime Verification Needed

After `docker compose up`, verify these manually:

1. **textmessagereceive endpoint:** Run inside the container:
   ```bash
   docker exec ts6-musicbot curl -s -H "X-API-Key: $TS_WEBQUERY_APIKEY" \
     http://ts.tendrolapio.cl:10081/1/textmessagereceive
   ```
   If 404 → switch `chat_listener.py` to Plan B (log parsing).

2. **TS6 URI argument:** Check if the client auto-connects via the `ts6server://` URI arg. If not, the `launch_ts6.sh` needs xdotool automation added.

3. **Microphone device name:** Verify the TS6 client sees `musicbot_sink.mic` in its audio settings. May need `pactl list sources` inside the container to confirm the exact name.
