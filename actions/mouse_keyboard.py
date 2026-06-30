import pyautogui

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.1


def click(x: int, y: int) -> None:
    pyautogui.click(x, y)


def type_text(text: str) -> None:
    pyautogui.typewrite(text, interval=0.05)


def press_key(key: str) -> None:
    pyautogui.press(key)


def scroll(x: int, y: int, direction: str, amount: int = 3) -> None:
    clicks = amount if direction == "up" else -amount
    pyautogui.scroll(clicks, x=x, y=y)
