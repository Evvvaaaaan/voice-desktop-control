#!/usr/bin/env python3
"""Throwaway preview of the notch HUD's per-state strip layout on hardware that
has NO physical notch.

Sets VOICEDESK_HUD_FAKE_NOTCH so the Swift HUD simulates a notch of the given
size, then cycles the active states so the left/right "ears" + the downward
transcript row can be eyeballed. Ends in idle so hover (peek) and click (pinned)
can be inspected by hand.

Run from the repo root:
    python3 scratch/preview_notch_hud.py            # default notch 200x37
    python3 scratch/preview_notch_hud.py 210x40     # custom WIDTHxHEIGHT (pt)

Ctrl+C to quit.
"""
import os
import sys
import time

# Must be set BEFORE the Swift bridge subprocess is spawned (it inherits env).
_fake = sys.argv[1] if len(sys.argv) > 1 else "200x37"
os.environ.setdefault("VOICEDESK_HUD_FAKE_NOTCH", _fake)

# Import after the env is set.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ui.notch_hud import NotchHUD  # noqa: E402

hud = NotchHUD()
hud.set_provider_info("macos", "claude", "claude-opus-4-8", "nvidia", "voice")
hud.show()
if not hud._initialized:
    print("HUD failed to start (Swift bridge). Are you on macOS with swiftc?")
    raise SystemExit(1)
print(f"Simulating notch = {os.environ['VOICEDESK_HUD_FAKE_NOTCH']} (WIDTHxHEIGHT pt)")
time.sleep(1.0)

# (state, transcript) — transcript drives the downward expansion below the notch.
sequence = [
    ("listening", ""),
    ("processing", "크롬 열어줘"),
    ("executing", "크롬 열어줘"),
    ("success", "크롬 열어줘"),
    ("error", "크롬 열어줘"),
    ("danger_confirm", ""),
]

try:
    for state, transcript in sequence:
        print(f"→ {state}  transcript={transcript!r}")
        hud.set_state(state)
        if state == "listening":
            hud.update_mic_level(0.6)   # harmless on a notched strip (no bars)
        time.sleep(1.2)
        if transcript:
            # A second render: the strip grows DOWN to reveal the transcript.
            hud.set_transcript(transcript)
            time.sleep(1.8)

    hud.set_state("idle")
    print("\nIdle. Hover the notch for the peek (시계/배터리); click to pin.")
    print("Ctrl+C to quit.")
    while True:
        time.sleep(1.0)
except KeyboardInterrupt:
    pass
finally:
    hud.hide()
