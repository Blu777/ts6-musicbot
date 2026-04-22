"""
Resolves a search query or URL to a streamable audio URL via yt-dlp.
Supports YouTube, SoundCloud, and any site yt-dlp handles (~1000+).

Cache dir is configurable via AUDIO_CACHE_DIR env var. Default: /tmp/musicbot_cache.
"""

import asyncio
import hashlib
import logging
import os
import shutil

import yt_dlp

log = logging.getLogger(__name__)

CACHE_DIR = os.getenv("AUDIO_CACHE_DIR", "/tmp/musicbot_cache")
# Hard cap for expanding playlists, to avoid accidental massive enqueues.
MAX_PLAYLIST_ITEMS = int(os.getenv("MAX_PLAYLIST_ITEMS", "100"))

_BASE_YDL_OPTS = {
    "format": "bestaudio",
    "quiet": True,
    "no_warnings": True,
    "extract_flat": False,
    # Be polite with YouTube
    "source_address": "0.0.0.0",
    "retries": 3,
}


def _ydl_opts(*, noplaylist: bool = True, flat: bool = False) -> dict:
    opts = dict(_BASE_YDL_OPTS)
    opts["noplaylist"] = noplaylist
    if flat:
        opts["extract_flat"] = "in_playlist"
    return opts


def clear_cache() -> None:
    """Delete all downloaded audio files from the cache directory."""
    if os.path.isdir(CACHE_DIR):
        shutil.rmtree(CACHE_DIR, ignore_errors=True)
        log.info("Cleared audio cache: %s", CACHE_DIR)


def delete_track_file(path: str) -> None:
    """Delete a single cached track file, ignoring errors."""
    try:
        os.remove(path)
    except OSError:
        pass


async def download_track(track: dict, progress_cb=None) -> str:
    """Download track audio to local cache. Returns the file path."""
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

    result_holder: list[str | None] = [None]

    def _download():
        opts = {
            **_ydl_opts(noplaylist=True),
            "outtmpl": out_tmpl,
            "progress_hooks": [_hook],
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(track["webpage_url"], download=True)
            if info and "entries" in info:
                info = info["entries"][0]
            result_holder[0] = ydl.prepare_filename(info)

    await loop.run_in_executor(None, _download)
    assert result_holder[0] is not None
    return result_holder[0]


async def resolve(query: str) -> dict:
    """
    Resolves a search query or URL to single-track metadata.
    Returns dict with: url, title, duration, webpage_url, uploader.
    Raises ValueError if nothing found.
    """
    search_query = query if query.startswith("http") else f"ytsearch1:{query}"
    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(
        None, lambda: _resolve_sync(search_query, noplaylist=True)
    )
    if info is None:
        raise ValueError(f"No results for: {query}")
    if "entries" in info:
        info = info["entries"][0]
    return _info_to_track(info, fallback_url=query)


async def resolve_playlist(url: str, limit: int | None = None) -> list[dict]:
    """Resolve a playlist URL to a list of track metadata dicts.

    Uses flat extraction first (cheap), then resolves each entry individually
    only when actually needed. To avoid long blocking calls, we return basic
    metadata and let the caller re_resolve or download_track per item.
    """
    max_items = min(limit or MAX_PLAYLIST_ITEMS, MAX_PLAYLIST_ITEMS)
    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(
        None, lambda: _resolve_sync(url, noplaylist=False, flat=True)
    )
    if info is None:
        raise ValueError(f"No playlist at: {url}")
    entries = info.get("entries") or []
    tracks: list[dict] = []
    for e in entries[:max_items]:
        if not e:
            continue
        webpage = e.get("url") or e.get("webpage_url")
        if not webpage:
            continue
        # Flat entries often give just an id; yt-dlp reconstructs the URL lazily.
        if webpage.startswith("http"):
            pass
        elif e.get("ie_key") == "Youtube":
            webpage = f"https://www.youtube.com/watch?v={webpage}"
        tracks.append({
            "url": e.get("url", ""),  # may be empty for flat; re_resolve on play
            "title": e.get("title", "Untitled"),
            "duration": e.get("duration", 0) or 0,
            "webpage_url": webpage,
            "uploader": e.get("uploader", ""),
        })
    return tracks


async def re_resolve(webpage_url: str) -> str:
    """Re-fetch a fresh stream URL from the track's webpage URL."""
    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(
        None, lambda: _resolve_sync(webpage_url, noplaylist=True)
    )
    if info is None:
        raise ValueError(f"Could not re-resolve {webpage_url}")
    if "entries" in info:
        info = info["entries"][0]
    return info["url"]


def _info_to_track(info: dict, fallback_url: str = "") -> dict:
    return {
        "url": info.get("url", ""),
        "title": info.get("title", "Untitled"),
        "duration": info.get("duration", 0) or 0,
        "webpage_url": info.get("webpage_url", fallback_url),
        "uploader": info.get("uploader", ""),
    }


def _resolve_sync(query: str, *, noplaylist: bool = True, flat: bool = False) -> dict:
    with yt_dlp.YoutubeDL(_ydl_opts(noplaylist=noplaylist, flat=flat)) as ydl:
        info = ydl.extract_info(query, download=False)
        if info is None:
            raise ValueError(f"No results for: {query}")
        return info
