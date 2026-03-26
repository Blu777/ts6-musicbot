import os
import tempfile
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ts6.chat_listener import ChatListener, _parse_line


# --- Unit tests for _parse_line ---

def test_parse_line_textmessage_format():
    line = "[2026-03-25 20:30:00.000] [info] textmessage targetmode=2 target=7 msg=!play song invokerid=2 invokername=Alice invokeruid=xxx"
    result = _parse_line(line)
    assert result is not None
    sender, msg = result
    assert sender == "Alice"
    assert "!play" in msg


def test_parse_line_notifytextmessage_format():
    line = "notifytextmessage targetmode=2 msg=hello world invokerid=3 invokername=Bob invokeruid=xxx"
    result = _parse_line(line)
    assert result is not None
    assert result[0] == "Bob"
    assert "hello" in result[1]


def test_parse_line_non_message_returns_none():
    line = "[2026-03-25 20:25:00.637] [error] Could not load ts3soundbackend_isSupported"
    assert _parse_line(line) is None


def test_parse_line_empty_returns_none():
    assert _parse_line("") is None


# --- Integration tests for ChatListener log polling ---

@pytest.mark.asyncio
async def test_listener_reads_new_lines_from_log(tmp_path):
    log_file = tmp_path / "ts5client_2026-01-01_00-00.log"
    log_file.write_text("")

    received = []

    async def callback(sender, text):
        received.append((sender, text))

    listener = ChatListener(MagicMock(), callback, poll_interval=0)

    with patch("ts6.chat_listener.TS6_LOG_DIR", str(tmp_path)):
        with patch("ts6.chat_listener._latest_log_path", return_value=str(log_file)):
            # First poll: set up the file position
            listener._log_path = str(log_file)
            listener._log_pos = 0

            # Write a channel message line
            msg_line = "[2026-01-01 00:00:01.000] [info] textmessage targetmode=2 target=7 msg=!skip invokerid=3 invokername=TestUser invokeruid=xxx\n"
            log_file.write_text(msg_line)

            await listener._poll()

    assert received == [("TestUser", "!skip")]


@pytest.mark.asyncio
async def test_listener_stop_terminates_loop(tmp_path):
    log_file = tmp_path / "ts5client_2026-01-01_00-00.log"
    log_file.write_text("")

    listener = ChatListener(MagicMock(), AsyncMock(), poll_interval=0)
    with patch("ts6.chat_listener._latest_log_path", return_value=str(log_file)):
        task = asyncio.create_task(listener.start())
        await asyncio.sleep(0.05)
        await listener.stop()
        await asyncio.wait_for(task, timeout=1.0)


@pytest.mark.asyncio
async def test_listener_handles_missing_log_gracefully():
    listener = ChatListener(MagicMock(), AsyncMock(), poll_interval=0)
    with patch("ts6.chat_listener._latest_log_path", return_value=None):
        # Should not raise
        task = asyncio.create_task(listener.start())
        await asyncio.sleep(0.05)
        await listener.stop()
        await asyncio.wait_for(task, timeout=1.0)
