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
