#!/usr/bin/env python3
"""Disable VAD / AGC / denoise / typing-suppression in the TS6 client config.

The TS6 desktop client persists its audio-preprocessor settings inside
`settings.db` (SQLite), in the JSON blob `json_blobs.audio_settings`.
This script opens that blob and flips every per-device preprocessor entry so
the captured audio from `musicbot_sink.mic` passes through untouched — no
voice-activity gating, no gain ride, no denoise artifacts.

Idempotent: safe to run on every boot. Exits 0 if `settings.db` or the
`audio_settings` row don't exist yet (first boot, before the TS6 client has
had a chance to initialize).

Usage:
    ts6_patch_audio.py [path/to/settings.db | path/to/config-dir]

If no argument is given, searches for `settings.db` under
`$TS6_CONFIG_DIR` (default `/data/ts6-config`), including the `Default/`
profile subdirectory that the TS6 client creates (same layout as the
Windows client: `.../TeamSpeak/Default/settings.db`).
"""

import glob
import json
import logging
import os
import sqlite3
import sys
import time

log = logging.getLogger("ts6_patch_audio")

# Values we enforce on every capture device's preprocessor block.
PREPROC_OVERRIDES: dict[str, object] = {
    "vad": False,
    "agc": False,
    "denoise": False,
    "typingSuppression": False,
}


def _patch_preproc(preproc: dict) -> bool:
    """Mutate `preproc` in place. Returns True if anything changed."""
    changed = False
    for k, v in PREPROC_OVERRIDES.items():
        if preproc.get(k) != v:
            preproc[k] = v
            changed = True
    return changed


def _walk_and_patch(audio_settings: dict) -> int:
    """Walk the audio_settings tree and patch every preprocessor block found.

    The TS6 shape (per slot) is roughly:
        {
          "mode": "",
          "device": {...},
          "ptt": {...},
          "devices": {
             "<backend name>": [
                 [<device_info_dict>, <preprocessor_dict>],
                 ...
             ]
          }
        }
    """
    patched = 0
    for slot in audio_settings.values():
        if not isinstance(slot, dict):
            continue
        devices = slot.get("devices")
        if not isinstance(devices, dict):
            continue
        for backend_entries in devices.values():
            if not isinstance(backend_entries, list):
                continue
            for pair in backend_entries:
                # Each entry is a [device_info, preprocessor_config] pair.
                if isinstance(pair, list) and len(pair) >= 2 \
                        and isinstance(pair[1], dict):
                    if _patch_preproc(pair[1]):
                        patched += 1
    return patched


def patch(db_path: str) -> int:
    """Apply the patch. Returns count of preprocessor blocks modified."""
    if not os.path.isfile(db_path):
        log.info("settings.db not found at %s — skipping (first boot?)", db_path)
        return 0

    # Retry briefly in case the TS6 client still holds a write lock.
    last_err: Exception | None = None
    for attempt in range(5):
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            break
        except sqlite3.OperationalError as e:
            last_err = e
            time.sleep(1)
    else:
        log.warning("Could not open %s: %s", db_path, last_err)
        return 0

    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT value FROM json_blobs WHERE key='audio_settings'"
        )
        row = cur.fetchone()
        if not row:
            log.info(
                "audio_settings row not present yet — skipping "
                "(TS6 client has not initialized audio config)"
            )
            return 0

        try:
            data = json.loads(row[0])
        except (TypeError, json.JSONDecodeError) as e:
            log.warning("audio_settings is not valid JSON: %s", e)
            return 0

        if not isinstance(data, dict):
            log.warning("audio_settings root is not a JSON object")
            return 0

        patched = _walk_and_patch(data)
        if patched == 0:
            log.info("No changes needed — VAD/AGC/denoise already disabled")
            return 0

        new_value = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        cur.execute(
            "UPDATE json_blobs SET value=?, timestamp=? WHERE key='audio_settings'",
            (new_value, int(time.time())),
        )
        conn.commit()
        log.info("Patched %d preprocessor block(s): %s",
                 patched, list(PREPROC_OVERRIDES))
        return patched
    finally:
        conn.close()


def resolve_db_path(arg: str | None) -> str:
    """Accept either a settings.db file or a config directory (with optional
    profile subdirs like `Default/`) and return the concrete db path.

    If no match is found, returns the most likely default path anyway so
    the caller's "file not found" log is descriptive.
    """
    if arg and os.path.isfile(arg):
        return arg

    # If arg points to a directory, use it as the search base; otherwise
    # fall back to $TS6_CONFIG_DIR (file-path args that don't exist are
    # treated as "default location unknown — search the env dir").
    if arg and os.path.isdir(arg):
        base = arg
    else:
        base = os.environ.get("TS6_CONFIG_DIR", "/data/ts6-config")
    candidates = [
        os.path.join(base, "settings.db"),
        os.path.join(base, "Default", "settings.db"),
    ]
    # Also scan one level of profile subdirectories (TS6 uses `Default/`
    # but a user could have several profiles).
    candidates.extend(sorted(glob.glob(os.path.join(base, "*", "settings.db"))))
    for path in candidates:
        if os.path.isfile(path):
            return path
    # Nothing found yet — return the classic expected location for a clean
    # "skipping (first boot?)" log message downstream.
    return os.path.join(base, "Default", "settings.db")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="[ts6_patch_audio] %(message)s",
    )
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    db_path = resolve_db_path(arg)
    patch(db_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
