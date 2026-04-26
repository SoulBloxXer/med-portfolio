# connect_bot.py — setup

Mass-connect on LinkedIn search results by automating the mouse.
Three button images, looped.

## 1. Install deps

```bash
pip install -r requirements.txt
```

(`pyautogui`, `opencv-python`, `pillow` get added.)

## 2. Grant macOS permissions

System Settings → Privacy & Security:
- **Accessibility** → enable Terminal (or iTerm, whatever you run Python from)
- **Screen Recording** → enable Terminal

Without these, pyautogui can't move the mouse or read the screen.

## 3. Take three screenshots into `connect_bot_assets/`

The script matches against these PNGs to find buttons. Crop tightly — just
the button pill, no surrounding whitespace or text.

Use **Shift-Cmd-4** on macOS, drag a tight rectangle, then move the saved
file from your Desktop into `connect_bot_assets/`.

| File | What to capture |
|---|---|
| `connect.png` | A blue **"+ Connect"** pill on the search results page. The blue one with the person-plus icon — NOT "Pending", "View", or "Message". |
| `send.png` | The blue **"Send without a note"** button inside the connect modal. NOT the white "Add a note" button. (Click Connect on someone manually first to get the modal to appear, then screenshot the blue button on the right.) |
| `next.png` | The **"Next"** pagination button at the bottom of the search results. |

Important: take all three at the **same Chrome zoom level and macOS theme**
(light/dark) you'll run the script with. If you change zoom or theme later,
retake them.

## 4. Run

1. Open LinkedIn, do your search, you should see the search results page with Connect/Pending/View buttons down the right side.
2. In a terminal: `python connect_bot.py`
3. Script prints "Starting in 5s — bring LinkedIn to the front." Switch back to Chrome.
4. Don't move your mouse. Watch it work.

## Behaviour

- Scans the visible page for `connect.png` matches.
- For each match: clicks it, waits for the modal, clicks `send.png`, moves on.
- If `send.png` doesn't appear within 3s (e.g. LinkedIn asked for an email instead), presses Escape and skips that person — does NOT count it.
- When no Connect buttons are visible, scrolls down. If still none, looks for `next.png` and clicks it. If no Next either, exits.
- Stops at `MAX_CONNECTIONS` (default 20, top of `connect_bot.py`).

## Tweaking

- **Cap per run:** edit `MAX_CONNECTIONS` at top of `connect_bot.py`. Keep it under ~30 to stay well below LinkedIn's weekly invite throttle (~100/week).
- **Match strictness:** if it's missing real Connect buttons, lower `CONFIDENCE` from 0.9 to 0.85. If it's matching wrong things, raise to 0.95.
- **Speed:** the `random.uniform(...)` delays (~1-2.5s between actions) are deliberately slow and humanlike. Don't crank them down — that's what makes LinkedIn's automation detection flag accounts.

## Aborting

Slam your mouse to any screen corner — pyautogui's failsafe kills the script instantly. Or just `Ctrl-C` in the terminal.

## Things to know

- LinkedIn ToS forbids UI automation. Account restriction is the realistic worst case if you blow past the invite cap. The defaults here are conservative; don't crank them.
- Mouse fights: don't touch the mouse during a run.
- Retake the templates if Chrome zoom or system theme changes — confidence matching is forgiving but not magic.
