# ui/animations.py
STATE_COLORS = {
    "idle":           (0.0, 0.0, 0.0, 0.0),       # Invisible/Bezel merged
    "listening":      (0.18, 0.50, 1.0, 0.95),    # Neon Blue Glow
    "processing":     (1.0, 0.60, 0.0, 0.95),     # Warm Orange
    "executing":      (0.12, 0.84, 0.38, 0.95),   # Fresh Green
    "success":        (0.0, 1.0, 0.40, 0.95),     # Emerald Success
    "error":          (1.0, 0.25, 0.25, 0.95),    # Crimson Red
    "danger_confirm": (1.0, 0.20, 0.20, 0.95),    # Critical Danger Alert
}

STATE_LABELS = {
    "idle":           "",
    "listening":      "듣고 있어요...",
    "processing":     "생각하는 중...",
    "executing":      "명령 수행 중...",
    "success":        "완료했습니다",
    "error":          "오류 발생",
    "danger_confirm": "안전 확인: 실행할까요?",
}
