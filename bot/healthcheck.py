"""
Docker healthcheck.

Returns 0 if:
  - Python bot process is running (main.py)
  - PulseAudio sink `musicbot_sink` exists
  - WebQuery API is reachable

Returns 1 otherwise.
"""

import asyncio
import os
import subprocess
import sys

from dotenv import load_dotenv

load_dotenv()


def _check_bot_process() -> bool:
    try:
        out = subprocess.run(
            ["pgrep", "-f", "bot/main.py"],
            capture_output=True, text=True, timeout=5,
        )
        return out.returncode == 0 and bool(out.stdout.strip())
    except Exception:
        return False


def _check_pulse_sink() -> bool:
    sink = os.getenv("PULSE_SINK_NAME", "musicbot_sink")
    try:
        out = subprocess.run(
            ["pactl", "list", "short", "sinks"],
            capture_output=True, text=True, timeout=5,
            env={**os.environ, "PULSE_SERVER": os.getenv("PULSE_SERVER", "unix:/tmp/pulse/native")},
        )
        return sink in out.stdout
    except Exception:
        return False


async def _check_webquery() -> bool:
    import aiohttp
    host = os.getenv("TS_WEBQUERY_HOST", "localhost")
    port = os.getenv("TS_WEBQUERY_PORT", "10081")
    key = os.getenv("TS_WEBQUERY_APIKEY", "")
    url = f"http://{host}:{port}/1/whoami"
    try:
        async with aiohttp.ClientSession(headers={"X-API-Key": key}) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                return resp.status == 200
    except Exception:
        return False


async def main() -> int:
    checks = {
        "bot_process": _check_bot_process(),
        "pulse_sink": _check_pulse_sink(),
        "webquery": await _check_webquery(),
    }
    ok = all(checks.values())
    status = "OK" if ok else "FAIL"
    print(f"{status}: {checks}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
