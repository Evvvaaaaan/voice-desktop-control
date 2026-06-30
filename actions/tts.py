import subprocess


def speak(text: str, voice: str = "Yuna", rate: int = 200) -> None:
    subprocess.run(["say", "-v", voice, "-r", str(rate), text], check=True)
