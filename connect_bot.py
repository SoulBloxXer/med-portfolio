"""LinkedIn mass-connect: click Connect -> click Send -> repeat -> click Next page."""
import time
from pathlib import Path

import pyautogui
import pyscreeze

A = Path(__file__).parent / "connect_bot_assets"
CONNECT = str(A / "connect.png")
SEND    = str(A / "send.png")
NEXT    = str(A / "next.png")

MAX = 500
CONF = 0.85

# Retina fix: locateOnScreen returns retina-pixel coords, click() needs logical.
SHOT_W, SHOT_H = pyautogui.screenshot().size
SCALE = SHOT_W / pyautogui.size()[0]

# Tight retina-pixel search regions (smaller = much faster).
# Connect column on the right side of search results (~60% screen width).
CONNECT_REGION = (int(SHOT_W * 0.55), 0, int(SHOT_W * 0.15), SHOT_H)
# Send button lives in right half of centered modal.
SEND_REGION = (int(SHOT_W * 0.40), int(SHOT_H * 0.30), int(SHOT_W * 0.35), int(SHOT_H * 0.40))
# Next button at bottom-right.
NEXT_REGION = (int(SHOT_W * 0.40), int(SHOT_H * 0.75), int(SHOT_W * 0.40), int(SHOT_H * 0.25))


def click(loc):
    pyautogui.click(loc.x / SCALE, loc.y / SCALE)


def find(img, timeout=0.4, region=None):
    end = time.time() + timeout
    while time.time() < end:
        try:
            return pyautogui.locateCenterOnScreen(
                img, confidence=CONF, region=region, grayscale=True
            )
        except (pyautogui.ImageNotFoundException, pyscreeze.ImageNotFoundException):
            pass
        time.sleep(0.02)
    return None


def main():
    print("Starting in 1s")
    time.sleep(1)

    count = 0
    nexts_in_row = 0
    fruitless_scrolls = 0
    recent_clicks = []  # list of (cx, cy) we've clicked since last scroll/next

    while count < MAX:
        try:
            raw = list(pyautogui.locateAllOnScreen(
                CONNECT, confidence=CONF, region=CONNECT_REGION, grayscale=True
            ))
        except (pyautogui.ImageNotFoundException, pyscreeze.ImageNotFoundException):
            raw = []

        # Dedupe by Y-row (LinkedIn rows are ~150 retina pixels tall, only
        # ONE Connect per row), and filter out rows we already clicked since
        # the last scroll/page change — those buttons may still be showing
        # as "Connect" while LinkedIn lags on the visual transition.
        ROW = 80  # half a row in retina pixels — anything closer is the same row
        positions = []
        for b in raw:
            cx, cy = b.left + b.width / 2, b.top + b.height / 2
            if any(abs(cy - p[1]) < ROW for p in positions):
                continue
            if any(abs(cy - r) < ROW for r in recent_clicks):
                continue
            positions.append((cx, cy))
        positions.sort(key=lambda p: p[1])

        if positions:
            nexts_in_row = 0
            fruitless_scrolls = 0
            for cx, cy in positions:
                if count >= MAX:
                    break
                pyautogui.click(cx / SCALE, cy / SCALE)
                recent_clicks.append(cy)
                s = find(SEND, timeout=0.8, region=SEND_REGION)
                if s:
                    click(s)
                    count += 1
                    print(f"{count}/{MAX}")
                else:
                    pyautogui.press("escape")
                    time.sleep(0.05)
            continue

        # No fresh Connects — try Next.
        n = find(NEXT, timeout=0.2, region=NEXT_REGION)
        if n:
            if nexts_in_row >= 5:
                print(f"5 Next clicks with no Connects. Done. {count} sent.")
                return
            click(n)
            nexts_in_row += 1
            recent_clicks.clear()
            time.sleep(1.2)
            continue

        # Scroll down — page positions change so clear recent.
        pyautogui.scroll(-5)
        time.sleep(0.1)
        recent_clicks.clear()
        fruitless_scrolls += 1
        if fruitless_scrolls >= 10:
            print(f"Nothing after 10 scrolls. Done. {count} sent.")
            return

    print(f"Done. {count} sent.")


if __name__ == "__main__":
    main()
