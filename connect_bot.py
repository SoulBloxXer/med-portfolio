"""LinkedIn mass-connect: click Connect -> click Send -> repeat -> click Next page."""
import time
from pathlib import Path

import pyautogui
import pyscreeze

A = Path(__file__).parent / "connect_bot_assets"
CONNECT = str(A / "connect.png")
SEND    = str(A / "send.png")
NEXT    = str(A / "next.png")

MAX = 100
CONF = 0.85

# Retina fix: locateOnScreen returns retina-pixel coords, click() needs logical.
SCALE = pyautogui.screenshot().size[0] / pyautogui.size()[0]


def click(loc):
    pyautogui.click(loc.x / SCALE, loc.y / SCALE)


def find(img, timeout=0.3):
    end = time.time() + timeout
    while time.time() < end:
        try:
            return pyautogui.locateCenterOnScreen(img, confidence=CONF)
        except (pyautogui.ImageNotFoundException, pyscreeze.ImageNotFoundException):
            pass
        time.sleep(0.04)
    return None


def main():
    print("Starting in 1s")
    time.sleep(1)

    count = 0
    nexts_in_row = 0
    fruitless_scrolls = 0

    while count < MAX:
        # 1. See Connect? Click it, then click Send.
        c = find(CONNECT)
        if c:
            nexts_in_row = 0
            fruitless_scrolls = 0
            click(c)
            time.sleep(0.25)
            s = find(SEND, timeout=1.0)
            if s:
                click(s)
                count += 1
                print(f"{count}/{MAX}")
                time.sleep(0.1)
            else:
                pyautogui.press("escape")
                time.sleep(0.1)
            continue

        # 2. No Connect. See Next? Click it.
        n = find(NEXT)
        if n:
            if nexts_in_row >= 5:
                print(f"5 Next clicks with no Connects. Done. {count} sent.")
                return
            click(n)
            nexts_in_row += 1
            fruitless_scrolls = 0
            time.sleep(1.5)
            continue

        # 3. Nothing visible. Scroll down to reveal more.
        pyautogui.scroll(-5)
        time.sleep(0.15)
        fruitless_scrolls += 1
        if fruitless_scrolls >= 10:
            print(f"Nothing found after 10 scrolls. Done. {count} sent.")
            return

    print(f"Done. {count} sent.")


if __name__ == "__main__":
    main()
