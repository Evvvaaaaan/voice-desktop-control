"""Throwaway probe: can we walk the frontmost app's AX tree via pyobjc,
and how long does it take? Run: python3 scratch/probe_ax.py"""
import time

import AppKit

try:
    import ApplicationServices as AS
    print("ApplicationServices import: OK")
except ImportError as e:
    print(f"ApplicationServices import FAILED: {e}")
    raise SystemExit(1)

print("trusted:", AS.AXIsProcessTrusted())

front = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
print("frontmost:", front.localizedName(), front.processIdentifier())

app = AS.AXUIElementCreateApplication(front.processIdentifier())
AS.AXUIElementSetMessagingTimeout(app, 0.3)

# Chromium/Electron apps only build the web-content AX tree when assistive
# tech announces itself. Both spellings are needed across app generations.
for flag in ("AXEnhancedUserInterface", "AXManualAccessibility"):
    err = AS.AXUIElementSetAttributeValue(app, flag, True)
    print(f"set {flag}: err={err}")
time.sleep(0.3)  # give the renderer a beat to build the tree


def attr(elem, name):
    err, val = AS.AXUIElementCopyAttributeValue(elem, name, None)
    return val if err == 0 else None


t0 = time.monotonic()
wins = attr(app, "AXWindows") or []
print(f"windows: {len(wins)}")

INTERACTIVE = {
    "AXButton", "AXLink", "AXTextField", "AXTextArea", "AXCheckBox",
    "AXRadioButton", "AXPopUpButton", "AXComboBox", "AXMenuButton",
    "AXMenuItem", "AXSlider", "AXDisclosureTriangle", "AXTabGroup",
}
seen_roles = {}

found = []
visited = 0


def center(elem):
    pos = attr(elem, "AXPosition")
    size = attr(elem, "AXSize")
    if pos is None or size is None:
        return None
    okp, p = AS.AXValueGetValue(pos, AS.kAXValueCGPointType, None)
    oks, s = AS.AXValueGetValue(size, AS.kAXValueCGSizeType, None)
    if not (okp and oks):
        return None
    return (p.x + s.width / 2, p.y + s.height / 2)


def walk(elem, depth):
    global visited
    if depth > 25 or visited > 6000 or len(found) >= 300:
        return
    visited += 1
    role = attr(elem, "AXRole")
    seen_roles[role] = seen_roles.get(role, 0) + 1
    if role in INTERACTIVE:
        title = attr(elem, "AXTitle") or attr(elem, "AXDescription") or attr(elem, "AXValue") or ""
        found.append((role, str(title)[:40], center(elem)))
    for child in (attr(elem, "AXChildren") or []):
        walk(child, depth + 1)


for w in wins[:2]:
    walk(w, 0)

elapsed = time.monotonic() - t0
print(f"visited={visited} interactive={len(found)} in {elapsed*1000:.0f}ms")
print("roles:", dict(sorted(seen_roles.items(), key=lambda kv: -kv[1])))
for role, title, c in found[:40]:
    print(f"  {role:22s} {title!r:44s} center={c}")
