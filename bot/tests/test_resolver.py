import pytest
from unittest.mock import patch

from audio.resolver import resolve, resolve_playlist


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

    def fake_sync(query, **kwargs):
        captured["query"] = query
        return FAKE_INFO

    with patch("audio.resolver._resolve_sync", side_effect=fake_sync):
        await resolve("rick astley")

    assert captured["query"].startswith("ytsearch1:")
    assert "rick astley" in captured["query"]


@pytest.mark.asyncio
async def test_resolve_raises_on_no_result():
    def fail(_q, **_kw):
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

    with patch("audio.resolver._resolve_sync", return_value=info_with_entries):
        track = await resolve("https://youtube.com/playlist?list=xxx")

    assert track["title"] == "Never Gonna Give You Up"


@pytest.mark.asyncio
async def test_resolve_playlist_extracts_entries():
    flat_info = {
        "entries": [
            {"url": "id1", "title": "A", "duration": 100, "ie_key": "Youtube"},
            {"url": "https://example.com/b", "title": "B", "duration": 200},
            {"url": "id3", "title": "C", "duration": 300, "ie_key": "Youtube"},
        ],
        "webpage_url": "https://youtube.com/playlist?list=xxx",
    }

    with patch("audio.resolver._resolve_sync", return_value=flat_info):
        tracks = await resolve_playlist("https://youtube.com/playlist?list=xxx")

    assert len(tracks) == 3
    assert tracks[0]["title"] == "A"
    assert tracks[0]["webpage_url"].startswith("https://www.youtube.com/watch?v=")
    assert tracks[1]["webpage_url"] == "https://example.com/b"


@pytest.mark.asyncio
async def test_resolve_playlist_respects_limit():
    flat_info = {
        "entries": [
            {"url": f"id{i}", "title": f"T{i}", "duration": 100, "ie_key": "Youtube"}
            for i in range(50)
        ],
    }
    with patch("audio.resolver._resolve_sync", return_value=flat_info):
        tracks = await resolve_playlist("https://x", limit=5)
    assert len(tracks) == 5
