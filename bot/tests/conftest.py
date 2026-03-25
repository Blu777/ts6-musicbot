import sys
import os
import pathlib

# Put bot/ on sys.path so tests can import ts6, audio, commands directly
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

os.environ.setdefault("TS_WEBQUERY_HOST", "localhost")
os.environ.setdefault("TS_WEBQUERY_PORT", "10081")
os.environ.setdefault("TS_WEBQUERY_APIKEY", "test-key")
os.environ.setdefault("TS_BOT_NICKNAME", "testbot")
os.environ.setdefault("AUDIO_VOLUME", "85")
