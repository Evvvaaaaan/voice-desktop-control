# setup.py
from setuptools import setup

APP = ["main.py"]
DATA_FILES = [("", ["config.yaml"])]
OPTIONS = {
    "argv_emulation": False,
    "packages": [
        "anthropic", "openai", "pyautogui", "pynput",
        "faster_whisper", "sounddevice", "numpy", "PIL",
        "rumps", "pyobjc", "AppKit", "Quartz", "yaml", "matplotlib",
        "openwakeword",
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

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
