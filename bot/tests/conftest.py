import pytest
import os

# Make bot/ the import root for all tests
os.environ.setdefault("TS_WEBQUERY_HOST", "localhost")
os.environ.setdefault("TS_WEBQUERY_PORT", "10081")
os.environ.setdefault("TS_WEBQUERY_APIKEY", "test-key")
os.environ.setdefault("TS_BOT_NICKNAME", "testbot")
os.environ.setdefault("AUDIO_VOLUME", "85")
