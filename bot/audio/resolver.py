"""
Resolves a search query or URL to a streamable audio URL via yt-dlp.
Supports YouTube, SoundCloud, and any site yt-dlp handles (~1000+).
"""

import asyncio
import hashlib
import os
import shutil
import yt_dlp

CACHE_DIR = "/tmp/musicbot_cache"

YDL_OPTS = {
    # Always pick the highest-quality audio stream available
    "format": "bestaudio",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "extract_flat": False,
}


def clear_cache() -> None:
    """Delete all downloaded audio files from the cache directory."""
    if os.path.isdir(CACHE_DIR):
        shutil.rmtree(CACHE_DIR, ignore_errors=True)


def delete_track_file(path: str) -> None:
    """Delete a single cached track file, ignoring errors."""
    try:
        os.remove(path)
    except OSError:
        pass


async def download_track(track: dict, progress_cb=None) -> str:
    """Download track audio to local cache. Returns the file path.

    progress_cb is an async callable(pct: int) called at ~25% intervals.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    uid = hashlib.md5(track["webpage_url"].encode()).hexdigest()[:12]
    out_tmpl = os.path.join(CACHE_DIR, uid + ".%(ext)s")

    loop = asyncio.get_running_loop()
    last_reported = [0]

    def _hook(d):
        if progress_cb is None:
            return
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            if total:
                pct = int(d.get("downloaded_bytes", 0) / total * 100)
                if pct - last_reported[0] >= 25:
                    last_reported[0] = pct
                    asyncio.run_coroutine_threadsafe(progress_cb(pct), loop)
        elif d["status"] == "finished":
            asyncio.run_coroutine_threadsafe(progress_cb(100), loop)

    result_holder = [None]

    def _download():
        opts = {
            "format": "bestaudio",
            "outtmpl": out_tmpl,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "progress_hooks": [_hook],
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(track["webpage_url"], download=True)
            if "entries" in info:
                info = info["entries"][0]
            result_holder[0] = ydl.prepare_filename(info)

    await loop.run_in_executor(None, _download)
    return result_holder[0]


async def resolve(query: str) -> dict:
    """
    Resolves a search query or URL to track metadata.
    Returns dict with: url, title, duration, webpage_url, uploader.
    Raises ValueError if nothing found.
    """
    import audio.resolver as _mod
    search_query = query if query.startswith("http") else f"ytsearch1:{query}"
    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(None, lambda: _mod._resolve_sync(search_query))
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


async def re_resolve(webpage_url: str) -> str:
    """Re-fetch a fresh stream URL from the track's webpage URL.
    Call this just before playback to avoid expired YouTube stream URLs.
    """
    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(None, lambda: _resolve_sync(webpage_url))
    if "entries" in info:
        info = info["entries"][0]
    return info["url"]


def _resolve_sync(query: str) -> dict:
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        info = ydl.extract_info(query, download=False)
        if info is None:
            raise ValueError(f"No results for: {query}")
        return info
