"""Probe 2: does Chrome expose web content after AXEnhancedUserInterface,
and does a native app (Finder) walk cleanly? Run: python3 scratch/probe_ax2.py"""
import time

import AppKit
import ApplicationServices as AS


def attr(elem, name):
    err, val = AS.AXUIElementCopyAttributeValue(elem, name, None)
    return val if err == 0 else None


def walk_stats(root, interactive_out, max_nodes=8000, max_depth=30):
    roles = {}
    stack = [(root, 0)]
    visited = 0
    while stack and visited < max_nodes:
        elem, d = stack.pop()
        if d > max_depth:
            continue
        visited += 1
        role = attr(elem, "AXRole")
        roles[role] = roles.get(role, 0) + 1
        if role in ("AXButton", "AXLink", "AXTextField", "AXCheckBox",
                    "AXPopUpButton", "AXMenuItem", "AXRadioButton"):
            t = attr(elem, "AXTitle") or attr(elem, "AXDescription") or ""
            interactive_out.append((role, str(t)[:40]))
        for c in (attr(elem, "AXChildren") or []):
            stack.append((c, d + 1))
    return visited, roles


def probe(app_name, pid):
    app = AS.AXUIElementCreateApplication(pid)
    AS.AXUIElementSetMessagingTimeout(app, 0.5)
    for flag in ("AXEnhancedUserInterface", "AXManualAccessibility"):
        AS.AXUIElementSetAttributeValue(app, flag, True)
    time.sleep(1.5)
    t0 = time.monotonic()
    inter = []
    total_visited = 0
    all_roles = {}
    for w in (attr(app, "AXWindows") or [])[:2]:
        v, roles = walk_stats(w, inter)
        total_visited += v
        for k, n in roles.items():
            all_roles[k] = all_roles.get(k, 0) + n
    dt = (time.monotonic() - t0) * 1000
    print(f"\n=== {app_name}: visited={total_visited} interactive={len(inter)} in {dt:.0f}ms")
    print("roles:", dict(sorted(all_roles.items(), key=lambda kv: -kv[1])[:12]))
    has_web = any((r or "").startswith("AXWeb") for r in all_roles)
    print("has AXWebArea:", has_web)
    for role, t in inter[:12]:
        print(f"  {role:16s} {t!r}")


running = {a.localizedName(): a.processIdentifier()
           for a in AppKit.NSWorkspace.sharedWorkspace().runningApplications()}
for name in ("Google Chrome", "Finder"):
    if name in running:
        probe(name, running[name])
    else:
        print(f"{name}: not running")
