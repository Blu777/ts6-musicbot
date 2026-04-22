"""Unit tests for the ServerQuery notify parser."""

from ts6.chat_listener import _parse_notify, _tokenize, _ts_decode


def test_parse_notify_basic():
    line = "notifytextmessage targetmode=2 msg=hello\\sworld invokerid=3 invokername=Bob invokeruid=xxx"
    result = _parse_notify(line)
    assert result == ("Bob", "hello world")


def test_parse_notify_fields_out_of_order():
    """Parser must be order-independent."""
    line = "notifytextmessage invokername=Alice targetmode=2 invokerid=5 msg=!play\\sfoo"
    result = _parse_notify(line)
    assert result == ("Alice", "!play foo")


def test_parse_notify_with_pipe_and_slash_escapes():
    line = "notifytextmessage msg=a\\pb\\/c invokername=Bob"
    assert _parse_notify(line) == ("Bob", "a|b/c")


def test_parse_notify_textmessage_log_format():
    """Client chat log emits `textmessage ...` lines (no notify prefix)."""
    line = "[2026-03-25 20:30:00.000] [info] textmessage targetmode=2 target=7 msg=hi invokerid=2 invokername=Alice invokeruid=xxx"
    assert _parse_notify(line) == ("Alice", "hi")


def test_parse_notify_ignores_non_message():
    assert _parse_notify("[info] Could not load backend") is None
    assert _parse_notify("") is None
    assert _parse_notify("notifyclientmoved clid=3 cid=5") is None


def test_parse_notify_missing_fields_returns_none():
    assert _parse_notify("notifytextmessage targetmode=2") is None
    assert _parse_notify("notifytextmessage msg=hi") is None  # no invokername


def test_tokenize_handles_empty_values():
    d = _tokenize("notifytextmessage msg= invokername=Bob")
    assert d["invokername"] == "Bob"
    assert d["msg"] == ""


def test_ts_decode_roundtrip():
    assert _ts_decode(r"a\sb\pc\\d\/e") == "a b|c\\d/e"
