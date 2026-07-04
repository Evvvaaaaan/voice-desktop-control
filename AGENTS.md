# VoiceDesk — Agent Instructions (Codex)

1. Follow the Fable Thinking Harness in `~/.codex/AGENTS.md` (loop:
   UNDERSTAND → INVESTIGATE → PLAN → ACT → VERIFY → REPORT; no fix without a
   reproduced root cause; no "done" claim without seen verification output).
2. Read `CLAUDE.md` in this directory before changing anything — it is the
   single source of truth for this project's commands, architecture map,
   runtime-harness rules, and conventions. It applies to you verbatim.
3. Verification baseline: `python3 -m pytest tests/ -q` must pass before and
   after your change (295 tests, fully mocked, no network).
