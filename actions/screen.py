import subprocess
import tempfile
import os


def take_screenshot() -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp_path = f.name
    try:
        subprocess.run(["screencapture", "-x", tmp_path], check=True)
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp_path)
