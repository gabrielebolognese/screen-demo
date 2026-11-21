---
name: screen-demo
description: Make a polished demo video (and a GIF) of any website or web app, by code. Claude looks at the page, plans a tour, and a script plays it in Chromium with a smooth cursor, real clicks, typing and eased scrolls, then renders a 1920x1080 (or vertical, or square) video with zooms on what matters, highlight rings, captions and a title card. Use when the user says "make a demo video of my site", "record my app", "product demo", "screen recording of this page", "make a GIF of my landing page for the README", "show how this works in a video", "walkthrough video", or gives a URL and wants a video of it.
---

# screen-demo

Turns a URL into a demo video. You are the director: you look at the page, write the tour as JSON, and the script plays it, captures the
page's own frames (never the desktop) and edits the video. Scrolls, the cursor's glide and typing are captured frame by frame at 30 fps, so
they are smooth even on a heavy page; what the page does by itself after a click or a load comes from the live screencast.

## Setup (once)

1. Python 3.10+ with Pillow and a recent Playwright: `python -m pip install -U playwright pillow`, then `python -m playwright install chromium`.
2. ffmpeg on PATH (`winget install ffmpeg`, `brew install ffmpeg`).

Check with `python tests/selftest.py` (a local page, no network, about a minute).

## Workflow

1. **Ask what the video is for:** the URL, the 2 to 4 things to show (the hero, a feature, the price, a sign-up flow), the format
   (`landscape` 16:9 for YouTube and READMEs, `vertical` 9:16 for Shorts and Reels, `square`), and whether they want a GIF. Only the user's
   own site or app, or a public page they are allowed to show.
2. **Look at the page:** `python scripts/demo.py inspect URL WORK [--format vertical]`. Read every `WORK/page-N.jpg` (the page in
   viewport-sized slices, every clickable element boxed with a red number) and `WORK/elements.txt`. A cookie banner or a pop-up shows
   up here: the tour's first step closes it (the "Reject" or "Close" button).
3. **Write `WORK/tour.json`** (format in [references/tour-format.md](references/tour-format.md)): a title card, then short steps. A good
   tour: a caption that says what the product does, a scroll to the first thing worth seeing, a zoom on it, a click or some typing that
   shows the product working, a highlight on the result, a caption per idea. 15 to 40 seconds. Targets are the numbers of inspect (`#12`),
   or `css=...` or `text=...`.
4. **Record:** `python scripts/demo.py record WORK/tour.json OUT [--gif]`. It plays the tour, prints every step that failed, and renders
   `OUT/demo.mp4` (and `OUT/demo.gif`).
5. **Look at `OUT/keys.jpg`** (a frame of every step) before you call it done: a zoom on the wrong thing, a caption over the point of the
   frame, a step that failed (the element moved or was hidden), a banner still in the way. To change only the captions, zooms or the title
   card, edit `OUT/tour.json` and run `python scripts/demo.py render OUT [--gif]` (no new recording); anything else, record again.
6. **Deliver:** the path of `demo.mp4` (and the GIF), its length, and one line per idea it shows.

## Rules

- Never log in with a password, never type a password or card number (the script refuses password and payment fields), never buy, send,
  post or delete anything, never submit a form with someone's personal data. A demo of a logged-in area needs the user to provide a test
  account's page themselves.
- Decline cookie banners (the least data) unless the user says otherwise.
- Keep captions short (3 to 8 words); one idea per caption; the video's own movement does the rest.
- Respect the site: no tour of a page the user may not show.

## Example

User: "make a 20 second demo of my landing page https://example.com for the README, show the signup"

You run inspect, read the 3 slices, see a cookie banner (#2 "Reject all"), the hero, a "Try it" field (#9) and a pricing card (#21); you
write a tour: a title card, click #2, caption "Notes that write themselves", type into #9, click #10, highlight the result, caption
"Free forever", scroll to #21, zoom; record with --gif, open keys.jpg, see the zoom framed the price well, and answer with demo.mp4 (21 s),
demo.gif (3 MB) and the four ideas.
