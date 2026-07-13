import subprocess
import tempfile
import os
import io


def _main_display_rect():
    """Global rect (x, y, w, h) of the main display — what a bare
    `screencapture` (no -R region) actually captures."""
    try:
        import Quartz
        m = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
        return (float(m.origin.x), float(m.origin.y),
                float(m.size.width), float(m.size.height))
    except Exception:
        try:
            import pyautogui
            w, h = pyautogui.size()
            return (0.0, 0.0, float(w), float(h))
        except Exception:
            return (0.0, 0.0, 1440.0, 900.0)


def active_screen_rect():
    """Global rect (x, y, w, h; top-left origin) of the display hosting the
    frontmost app's window, falling back to the main display.

    Computer-use must capture and click the screen the user is actually
    working on — with multiple displays, the main display is often the
    wrong one (e.g. an external monitor at negative x).
    """
    try:
        import Quartz
        import AppKit

        center = None
        front = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        if front is not None:
            pid = front.processIdentifier()
            wins = Quartz.CGWindowListCopyWindowInfo(
                Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
            )
            for w in wins or []:
                if (w.get("kCGWindowOwnerPID") == pid
                        and w.get("kCGWindowLayer") == 0):
                    b = w.get("kCGWindowBounds") or {}
                    center = (b["X"] + b["Width"] / 2.0,
                              b["Y"] + b["Height"] / 2.0)
                    break

        if center is not None:
            err, ids, cnt = Quartz.CGGetActiveDisplayList(16, None, None)
            for d in (ids or [])[:cnt]:
                b = Quartz.CGDisplayBounds(d)
                if (b.origin.x <= center[0] <= b.origin.x + b.size.width
                        and b.origin.y <= center[1] <= b.origin.y + b.size.height):
                    return (float(b.origin.x), float(b.origin.y),
                            float(b.size.width), float(b.size.height))

        return _main_display_rect()
    except Exception:
        return _main_display_rect()


# The rect (x, y, w, h) the most recently captured screenshot actually
# covers. Normally equal to active_screen_rect() at capture time, but when
# the region capture fails (see _capture_active_display_png) the fallback
# plain `screencapture` grabs the MAIN display instead of whatever
# active_screen_rect() had resolved (e.g. an external monitor) — so this can
# legitimately differ from a fresh active_screen_rect() call. Click/move
# dispatch reads this (agent/tools.py's _to_logical) instead of recomputing
# active_screen_rect() itself, so a click is always mapped against the exact
# display the model was actually shown, never a different one resolved a
# moment later (e.g. after a focus change moved the "active" display).
_last_capture_rect = None


def last_capture_rect():
    return _last_capture_rect


# Target long edge after downscale. High enough that small buttons/text stay
# legible to the vision model (a low-res image is the #1 cause of misclicks),
# low enough to stay comfortably under the ~5MB base64 request cap most vision
# APIs enforce. JPEG at this size is typically 200-500KB.
_MAX_EDGE = 1568


def _capture_active_display_png(tmp_path: str, with_cursor: bool = False) -> None:
    global _last_capture_rect
    rx, ry, rw, rh = active_screen_rect()
    region = f"{rx},{ry},{rw},{rh}"
    flags = ["-x", "-C"] if with_cursor else ["-x"]
    res = subprocess.run(["screencapture", *flags, "-R", region, tmp_path],
                         capture_output=True)
    if res.returncode != 0 or os.path.getsize(tmp_path) == 0:
        # The requested region capture failed (observed with negative-origin
        # regions, e.g. an external monitor placed left of the main display)
        # — screencapture then falls back to its default, the MAIN display,
        # not the display active_screen_rect() resolved. _last_capture_rect
        # must reflect that or later clicks get mapped against the wrong
        # (unshown) display's coordinate space.
        subprocess.run(["screencapture", *flags, tmp_path], check=True)
        _last_capture_rect = _main_display_rect()
    else:
        _last_capture_rect = (rx, ry, rw, rh)


def take_screenshot() -> bytes:
    """Capture the display the user is working on, downscaled to fit vision
    API payload limits (see active_screen_rect)."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp_path = f.name
    try:
        _capture_active_display_png(tmp_path)
        try:
            subprocess.run(
                ["sips", "--resampleHeightWidthMax", str(_MAX_EDGE), tmp_path],
                check=True, capture_output=True,
            )
        except Exception:
            pass
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp_path)


def take_screenshot_with_grid(with_cursor: bool = True) -> bytes:
    """Screenshot with a coordinate grid overlay, for accurate computer-use
    clicking.

    The agent reports click targets on a normalized 0..1000 grid (see
    agent/tools.py's _to_logical). Asking a vision model to eyeball a raw
    screenshot and guess that grid position is the single biggest source of
    misclicks — models are decent at reading an overlaid ruler but poor at
    estimating unmarked fractional position. This burns the same 0/100/.../900
    grid directly into the image with axis labels, so the model can read the
    target coordinate off the gridlines context clues instead of estimating it.

    `with_cursor` (default True) includes the real pointer in the capture, so
    after a move_mouse the model can SEE exactly where the cursor landed
    relative to its intended target and correct before clicking — the
    move-then-verify-then-click pattern described in the system prompt.
    """
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp_path = f.name
    try:
        _capture_active_display_png(tmp_path, with_cursor=with_cursor)
        try:
            from PIL import Image, ImageDraw, ImageFont

            img = Image.open(tmp_path).convert("RGB")
            w, h = img.size
            draw = ImageDraw.Draw(img, "RGBA")
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 15)
            except Exception:
                font = ImageFont.load_default()

            line_color = (0, 255, 140, 110)
            label_bg = (0, 0, 0, 170)
            label_fg = (0, 255, 140, 255)

            for i in range(1, 10):
                x = round(i / 10.0 * w)
                draw.line([(x, 0), (x, h)], fill=line_color, width=1)
                y = round(i / 10.0 * h)
                draw.line([(0, y), (w, y)], fill=line_color, width=1)

            for i in range(0, 10):
                gx = round(i / 10.0 * w)
                label = str(i * 100)
                tb = draw.textbbox((0, 0), label, font=font)
                tw, th = tb[2] - tb[0], tb[3] - tb[1]
                draw.rectangle([gx + 2, 2, gx + 6 + tw, 6 + th], fill=label_bg)
                draw.text((gx + 4, 2), label, fill=label_fg, font=font)

                gy = round(i / 10.0 * h)
                if i == 0:
                    continue
                label = str(i * 100)
                tb = draw.textbbox((0, 0), label, font=font)
                tw, th = tb[2] - tb[0], tb[3] - tb[1]
                draw.rectangle([2, gy + 2, 6 + tw, gy + 6 + th], fill=label_bg)
                draw.text((4, gy + 4), label, fill=label_fg, font=font)

            scale = min(1.0, _MAX_EDGE / max(w, h))
            if scale < 1.0:
                img = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)

            # PNG, not JPEG: the thin gridlines/labels are the whole point of
            # this function, and JPEG's block compression smears exactly
            # those fine, high-contrast edges — undermining the accuracy this
            # overlay exists to provide. Screenshots are mostly flat UI color,
            # so PNG size stays reasonable even at this resolution.
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            return buf.getvalue()
        except Exception:
            # Grid overlay is a precision aid, not a requirement — a plain
            # screenshot is still far better than failing the observation.
            try:
                subprocess.run(
                    ["sips", "--resampleHeightWidthMax", str(_MAX_EDGE), tmp_path],
                    check=True, capture_output=True,
                )
            except Exception:
                pass
            with open(tmp_path, "rb") as f:
                return f.read()
    finally:
        os.unlink(tmp_path)
