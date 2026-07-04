# VoiceDesk — Project Guide

Korean voice-controlled macOS desktop agent: wake word → STT → LLM ReAct loop
→ macOS actions (apps, browser, mouse/keyboard, AppleScript) → TTS reply, with
a Swift notch HUD. The global Fable Thinking Harness (`~/CLAUDE.md`) applies
to all work here.

## Commands

```bash
pip3 install -r requirements.txt   # install deps (Python 3.12+)
python3 -m pytest tests/ -q        # full test suite — run BEFORE and AFTER changes
python3 main.py                    # run the app (needs macOS permissions, see SETUP.md)
./build_dmg.sh                     # build .app / DMG (py2app)
```

## Architecture map

| Path          | Role |
|---------------|------|
| `main.py`     | Orchestrator: wires components, menu bar, config hot-reload |
| `activation/` | Wake word (openwakeword) + hotkey |
| `stt/`        | Speech-to-text adapters (whisper local/API, macOS) |
| `llm/`        | Provider adapters (Claude, OpenAI, NVIDIA, Ollama) — all share ONE system prompt |
| `agent/`      | The runtime harness: `context.py` (SYSTEM_PROMPT, conversation window), `core.py` (ReAct loop), `tools.py` (action dispatch), `cache.py` (hot-command cache) |
| `actions/`    | macOS effectors: AppleScript, mouse/keyboard, screen, TTS |
| `safety/`     | SafetyGuard — blocks/confirms dangerous actions |
| `routines/`   | Repeated-command detection and saved routines |
| `metrics/`    | Command success/latency collection |
| `ui/`         | Notch HUD (Swift, auto-compiled), settings window, menu bar |

## Runtime harness rules (do not weaken)

The agent loop in `agent/core.py` enforces the same harness the docs describe:

- **Verify before done**: `done=true` is REJECTED when the final action's
  dispatch returned an error; the error observation is fed back so the model
  retries or reports failure honestly. Covered by
  `tests/test_agent.py::test_done_rejected_when_final_action_fails_then_recovers`.
- **No false success claims**: a failing command must never speak the model's
  success text; the honest fallback is used. Covered by
  `test_false_success_claim_never_spoken_when_action_keeps_failing`.
- **Cache safety**: only single-step, non-error, non-speak_only actions may be
  cached (replay safety).
- The system prompt lives ONLY in `agent/context.py` — never add per-adapter
  prompts in `llm/*`.

## Project conventions

- Tests are fully mocked — no network, no real mouse/screen access in tests.
- Known issue: the suite has rare order-dependent flakes
  (`test_stt.py::test_whisper_local_adapter`,
  `test_llm.py::test_claude_supports_vision_and_builds_image_observation`);
  each passes in isolation. Re-run before blaming your change.
- User-facing strings (spoken responses, HUD text) are Korean; code,
  comments, and commit messages are English.
- `scratch/` holds throwaway diagnostics — don't import from it.
