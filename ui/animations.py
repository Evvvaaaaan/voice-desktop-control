# ui/animations.py
STATE_COLORS = {
    "idle":           (0.1, 0.1, 0.1, 0.6),
    "listening":      (0.2, 0.6, 1.0, 0.9),
    "processing":     (0.8, 0.5, 0.0, 0.9),
    "executing":      (0.3, 0.8, 0.3, 0.9),
    "success":        (0.0, 1.0, 0.4, 0.9),
    "error":          (1.0, 0.2, 0.2, 0.9),
    "danger_confirm": (1.0, 0.8, 0.0, 0.9),
}

STATE_LABELS = {
    "idle":           "",
    "listening":      "🎤",
    "processing":     "⚙️",
    "executing":      "▶",
    "success":        "✓",
    "error":          "✕",
    "danger_confirm": "⚠️ 진행할까요?",
}
