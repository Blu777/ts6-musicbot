#!/usr/bin/env python3
"""Read-only audit of the TS6 audio preprocessor state.

Prints the currently-selected capture device per slot, its preprocessor
flags (VAD/AGC/denoise/typing-suppression), and a summary of how many
preprocessor blocks have each flag on/off. Handy to run inside the
container to answer "is VAD actually off right now?".

    docker exec <container> python3 /app/scripts/ts6_audit_audio.py
"""

import json
import os
import sqlite3
import sys

# Reuse the patcher's path discovery so both scripts look in the same places
# (handles the `Default/` profile subdirectory that the TS6 client creates).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ts6_patch_audio import resolve_db_path  # noqa: E402


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    db_path = resolve_db_path(arg)

    if not os.path.isfile(db_path):
        print(f"[audit] settings.db not found at {db_path}")
        return 1

    try:
        conn = sqlite3.connect(db_path, timeout=5)
    except sqlite3.OperationalError as e:
        print(f"[audit] could not open {db_path}: {e}")
        return 1

    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM json_blobs WHERE key='audio_settings'")
        row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        print("[audit] audio_settings row not present — TS6 has not "
              "initialized its audio config yet")
        return 1

    try:
        data = json.loads(row[0])
    except (TypeError, json.JSONDecodeError) as e:
        print(f"[audit] audio_settings is not valid JSON: {e}")
        return 1

    flags = ("vad", "agc", "denoise", "typingSuppression")
    totals = {k: {"true": 0, "false": 0, "missing": 0} for k in flags}
    total_blocks = 0

    for slot_name, slot in data.items():
        if not isinstance(slot, dict):
            continue
        dev = slot.get("device") or {}
        print(f"\n── slot {slot_name} ({'capture' if dev.get('formFactor') == 2 else 'playback' if dev.get('formFactor') == 1 else '?'}) ──")
        print(f"  selected device: {dev.get('name', '(none)')}")
        print(f"  mode:            {slot.get('mode', '(empty)')}")
        ptt = slot.get("ptt")
        if isinstance(ptt, dict):
            print(f"  ptt.active:      {ptt.get('active')}")
        # Find preprocessor for the selected device only (quick status)
        sel_id = dev.get("id")
        selected_preproc = None
        for backend_entries in (slot.get("devices") or {}).values():
            if not isinstance(backend_entries, list):
                continue
            for entry in backend_entries:
                if not (isinstance(entry, list) and len(entry) >= 2):
                    continue
                if not isinstance(entry[1], dict):
                    continue
                total_blocks += 1
                preproc = entry[1]
                for k in flags:
                    if k in preproc:
                        totals[k]["true" if preproc[k] else "false"] += 1
                    else:
                        totals[k]["missing"] += 1
                if isinstance(entry[0], dict) and entry[0].get("id") == sel_id:
                    selected_preproc = preproc
        if selected_preproc is not None:
            print("  preprocessor for selected device:")
            for k in flags:
                print(f"    {k:20s} = {selected_preproc.get(k, '(missing)')}")
        else:
            print("  (no preprocessor entry matched the selected device)")

    print(f"\n── totals across {total_blocks} preprocessor block(s) ──")
    for k in flags:
        t = totals[k]
        print(f"  {k:20s} true={t['true']:3d}  false={t['false']:3d}  missing={t['missing']:3d}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
