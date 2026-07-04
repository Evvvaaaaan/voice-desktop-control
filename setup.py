# setup.py
import os
import subprocess
import sys
from setuptools import find_packages, setup

APP = ["main.py"]
SWIFT_HUD_SOURCE = "ui/swift_hud/VoiceDeskHUD.swift"
SWIFT_HUD_BINARY = "build/VoiceDeskHUD"
DATA_FILES = [("", ["config.yaml"]), ("swift_hud", [SWIFT_HUD_SOURCE])]
OPTIONS = {
    "argv_emulation": False,
    "packages": [
        "anthropic", "openai", "pyautogui", "pynput",
        "faster_whisper", "sounddevice", "numpy", "PIL",
        "rumps", "objc", "AppKit", "Quartz", "AVFoundation", "yaml",
        "openwakeword",
    ],
    "excludes": [
        "matplotlib", "tkinter", "tests", "pytest",
        "rubicon", "mouseinfo", "pygetwindow",
    ],
    "plist": {
        "CFBundleName": "VoiceDesk",
        "CFBundleDisplayName": "VoiceDesk",
        "CFBundleVersion": "0.1.0",
        "NSMicrophoneUsageDescription": "VoiceDesk needs microphone access to hear voice commands.",
        "NSSpeechRecognitionUsageDescription": "VoiceDesk uses speech recognition to understand commands.",
        "NSAccessibilityUsageDescription": "VoiceDesk needs accessibility access to control your Mac.",
    },
}

SETUP_KWARGS = {}
if "py2app" in sys.argv:
    from py2app.build_app import py2app as _py2app

    try:
        os.makedirs(os.path.dirname(SWIFT_HUD_BINARY), exist_ok=True)
        subprocess.run(
            ["swiftc", SWIFT_HUD_SOURCE, "-o", SWIFT_HUD_BINARY],
            check=True,
            capture_output=True,
            text=True,
        )
        DATA_FILES.append(("swift_hud", [SWIFT_HUD_BINARY]))
    except Exception as exc:
        print(f"Warning: could not build Swift HUD helper: {exc}")

    class _VoiceDeskPy2App(_py2app):
        def finalize_options(self):
            self.distribution.install_requires = []
            super().finalize_options()

    SETUP_KWARGS["cmdclass"] = {"py2app": _VoiceDeskPy2App}

setup(
    app=APP,
    packages=find_packages(exclude=("tests*", "build*", "dist*", "data*")),
    py_modules=["main"],
    include_package_data=False,
    package_data={"ui.swift_hud": ["VoiceDeskHUD.swift"]},
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    **SETUP_KWARGS,
)
