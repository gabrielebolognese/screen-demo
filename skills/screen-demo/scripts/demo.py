#!/usr/bin/env python3
"""screen-demo: a polished demo video of any website, made by code. Claude plans the tour; this script plays it in Chromium with a smooth
cursor, real clicks, typing and eased scrolls, captures the page's own frames, and renders a video with zooms, highlight rings, captions
and a title card, plus a GIF for READMEs.

    python demo.py inspect URL WORK [--format landscape|vertical|square]
        WORK/page-1.jpg ...: the page in viewport-sized slices with every clickable element boxed and numbered; WORK/elements.json (number,
        tag, text, selector, box in page pixels); WORK/page.json
    python demo.py record TOUR OUT [--gif] [--headed]
        plays the tour and writes OUT/demo.mp4, OUT/keys.jpg (a frame of every step, to check), OUT/log.json (what happened when),
        OUT/demo.gif with --gif; the raw frames stay in OUT/frames/ until the render succeeds
    python demo.py render OUT [--gif]
        renders OUT/demo.mp4 again from the recorded frames (after changing a caption, a zoom or the title card in OUT/tour.json)

The tour format is in ../references/tour-format.md. Needs Python 3.10+ with Pillow and a recent Playwright with Chromium
(python -m pip install -U playwright pillow, then python -m playwright install chromium), and ffmpeg on PATH.
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
FONT = os.path.join(SKILL, "fonts", "Inter-Variable.ttf")
FPS = 30
FORMATS = {"landscape": (1280, 720, 1.5), "vertical": (432, 768, 2.5), "square": (720, 720, 1.5)}
ACCENT = (232, 50, 43)

CURSOR_JS = r"""
(() => {
  if (window.__dc) return;
  let el = null, x = -100, y = -100;
  const make = () => {
    const c = document.createElement('div');
    c.id = '__dc_cursor';
    c.innerHTML = '<svg width="30" height="30" viewBox="0 0 24 24"><path d="M3 2l7.6 19.2 2.7-7.6 7.6-2.7z" fill="#fff" stroke="#111" stroke-width="1.7" stroke-linejoin="round"/></svg>';
    Object.assign(c.style, {position: 'fixed', left: '-100px', top: '-100px', zIndex: '2147483647', pointerEvents: 'none', transform: 'translate(-3px,-2px)',
      filter: 'drop-shadow(0 2px 3px rgba(0,0,0,.35))'});
    (document.body || document.documentElement).appendChild(c);
    return c;
  };
  const get = () => { if (!el || !el.isConnected) el = document.getElementById('__dc_cursor') || make(); return el; };
  const ease = p => p < .5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
  window.__dc = {
    place(nx, ny) { x = nx; y = ny; const c = get(); c.style.left = x + 'px'; c.style.top = y + 'px'; return true; },
    move(nx, ny, ms) {
      const c = get(), x0 = x, y0 = y, t0 = performance.now();
      return new Promise(res => { const step = now => { const p = Math.min(1, (now - t0) / ms), e = ease(p);
        x = x0 + (nx - x0) * e; y = y0 + (ny - y0) * e; c.style.left = x + 'px'; c.style.top = y + 'px';
        if (p < 1) requestAnimationFrame(step); else res(true); }; requestAnimationFrame(step); });
    },
    ripple(rx, ry) {
      const r = document.createElement('div');
      Object.assign(r.style, {position: 'fixed', left: (rx - 22) + 'px', top: (ry - 22) + 'px', width: '44px', height: '44px', borderRadius: '50%',
        border: '4px solid rgba(232,50,43,.95)', zIndex: '2147483646', pointerEvents: 'none', transform: 'scale(.3)', opacity: '1',
        transition: 'transform .45s ease-out, opacity .45s ease-out'});
      (document.body || document.documentElement).appendChild(r);
      requestAnimationFrame(() => requestAnimationFrame(() => { r.style.transform = 'scale(1.7)'; r.style.opacity = '0'; }));
      setTimeout(() => r.remove(), 700); return true;
    },
    scroll(toY, ms) {
      const y0 = window.scrollY, max = document.documentElement.scrollHeight - innerHeight, y1 = Math.max(0, Math.min(max, toY)), t0 = performance.now();
      return new Promise(res => { const step = now => { const p = Math.min(1, (now - t0) / ms);
        window.scrollTo(0, y0 + (y1 - y0) * ease(p)); if (p < 1) requestAnimationFrame(step); else res(window.scrollY); }; requestAnimationFrame(step); });
    },
    pos() { return [x, y]; }
  };
  document.addEventListener('DOMContentLoaded', () => window.__dc.place(x, y));
})();
"""

ELEMENTS_JS = r"""
() => {
  const sel = 'a[href],button,input:not([type=hidden]),textarea,select,summary,[role=button],[role=link],[role=tab],[role=menuitem],[onclick],label[for]';
  const path = e => {
    if (e.id && document.querySelectorAll('#' + CSS.escape(e.id)).length === 1) return '#' + CSS.escape(e.id);
    const parts = [];
    while (e && e.nodeType === 1 && e !== document.body) {
      let p = e.tagName.toLowerCase();
      if (e.id && document.querySelectorAll('#' + CSS.escape(e.id)).length === 1) { parts.unshift('#' + CSS.escape(e.id)); break; }
      const sib = [...e.parentNode.children].filter(c => c.tagName === e.tagName);
      if (sib.length > 1) p += ':nth-of-type(' + (sib.indexOf(e) + 1) + ')';
      parts.unshift(p); e = e.parentElement;
    }
    return parts.join(' > ');
  };
  const out = [];
  document.querySelectorAll(sel).forEach(e => {
    const r = e.getBoundingClientRect(), st = getComputedStyle(e);
    if (r.width < 6 || r.height < 6 || st.visibility === 'hidden' || st.display === 'none' || parseFloat(st.opacity) === 0) return;
    const text = (e.innerText || e.value || e.getAttribute('aria-label') || e.getAttribute('placeholder') || e.getAttribute('title') || e.getAttribute('alt') || '')
      .trim().replace(/\s+/g, ' ').slice(0, 70);
    out.push({tag: e.tagName.toLowerCase(), type: (e.getAttribute('type') || ''), text, selector: path(e),
              box: [Math.round(r.left + scrollX), Math.round(r.top + scrollY), Math.round(r.width), Math.round(r.height)]});
  });
  out.sort((a, b) => a.box[1] - b.box[1] || a.box[0] - b.box[0]);
  return out.slice(0, 220);
}
"""


def say(msg: str) -> None:
    print(msg, flush=True)


def need_playwright():
    try:
        from playwright.sync_api import sync_playwright, Page
    except ImportError:
        raise SystemExit("Playwright is missing: python -m pip install -U playwright, then python -m playwright install chromium")
    if not hasattr(Page, "screencast"):
        raise SystemExit("this Playwright is too old for page.screencast: python -m pip install -U playwright")
    return sync_playwright


def font(size: int):
    from PIL import ImageFont
    try:
        f = ImageFont.truetype(FONT, size)
        try:
            f.set_variation_by_name("Bold")
        except Exception:
            pass
        return f
    except OSError:
        return ImageFont.load_default()


def write_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- inspect

def cmd_inspect(a) -> int:
    from PIL import Image, ImageDraw
    sync_playwright = need_playwright()
    vw, vh, _ = FORMATS[a.format]
    os.makedirs(a.work, exist_ok=True)
    for f in os.listdir(a.work):
        if f.startswith("page-") and f.endswith(".jpg"):
            os.remove(os.path.join(a.work, f))
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        pg = br.new_page(viewport={"width": vw, "height": vh}, device_scale_factor=1, locale="en-US")
        pg.goto(a.url, wait_until="load", timeout=60000)
        pg.wait_for_timeout(1500)
        els = pg.evaluate(ELEMENTS_JS)
        title = pg.title()
        height = pg.evaluate("() => document.documentElement.scrollHeight")
        full = os.path.join(a.work, "full.png")
        pg.screenshot(path=full, full_page=True)
        br.close()
    for i, e in enumerate(els, 1):
        e["n"] = i
    im = Image.open(full).convert("RGB")
    os.remove(full)
    d = ImageDraw.Draw(im)
    f = font(13)
    for e in els:
        x, y, w, h = e["box"]
        d.rectangle([x, y, x + w, y + h], outline=ACCENT, width=2)
        lab = str(e["n"])
        tw = d.textlength(lab, font=f)
        d.rectangle([x, max(0, y - 16), x + tw + 6, max(0, y - 16) + 16], fill=ACCENT)
        d.text((x + 3, max(0, y - 16)), lab, font=f, fill=(255, 255, 255))
    slices = []
    for k in range(min(10, math.ceil(im.height / vh))):
        part = im.crop((0, k * vh, im.width, min(im.height, (k + 1) * vh)))
        p = os.path.join(a.work, f"page-{k + 1}.jpg")
        part.save(p, quality=85)
        slices.append(p)
    write_json(os.path.join(a.work, "elements.json"), els)
    write_json(os.path.join(a.work, "page.json"), {"url": a.url, "title": title, "height": height, "viewport": [vw, vh], "format": a.format,
                                                   "slices": slices})
    with open(os.path.join(a.work, "elements.txt"), "w", encoding="utf-8", newline="\n") as fh:
        for e in els:
            fh.write(f"#{e['n']} {e['tag']}{'[' + e['type'] + ']' if e['type'] else ''} \"{e['text']}\" at y {e['box'][1]}\n")
    say(f"{title!r}: {height} px tall, {len(els)} clickable elements, {len(slices)} slices:")
    for s in slices:
        say(f"  {os.path.normpath(s)}")
    say(f"the elements by number: {os.path.normpath(os.path.join(a.work, 'elements.txt'))}")
    return 0


# ---------------------------------------------------------------- record

class Player:
    """Plays the tour on two clocks. The page's own reactions (after a click, a load, a wait) come from the live screencast; scripted motion
    (a scroll, the cursor's glide, typing) is captured stepped: the position is set and a screenshot taken for every frame at 30 fps, on a
    virtual clock, so it is smooth however slowly the page draws. Every time in the log and the frames is on the virtual clock."""

    def __init__(self, page, els: list, fdir: str):
        self.page, self.els, self.fdir = page, els, fdir
        self.frames = []
        self.offset = 0.0          # real seconds spent capturing stepped motion beyond its virtual length
        self.live = False
        self.floor = 0.0           # no live frame may land before the end of the last stepped stretch
        self.errors = []
        self.cur = (0.0, 0.0)

    def now(self) -> float:
        return time.time() - self.offset

    def add(self, data: bytes, t: float) -> None:
        name = f"f{len(self.frames):05d}.jpg"
        with open(os.path.join(self.fdir, name), "wb") as fh:
            fh.write(data)
        self.frames.append({"t": t, "file": name})

    def on_frame(self, fr) -> None:
        if not self.live:
            return
        try:
            t = float(fr["timestamp"]) / 1000.0 - self.offset
            if t >= self.floor:
                self.add(fr["data"], t)
        except Exception as exc:  # a frame that cannot be written must not break the page's event loop
            self.errors.append(str(exc)[:120])

    def stepped(self, setter, seconds: float) -> None:
        n = max(2, int(round(seconds * FPS)))
        self.live = False
        real0, v0 = time.time(), self.now()
        for k in range(n + 1):
            setter(k / n)
            self.add(self.page.screenshot(type="jpeg", quality=88), v0 + seconds * k / n)
        self.offset += (time.time() - real0) - seconds
        self.floor = v0 + seconds + 0.001
        self.live = True

    def field(self, target):
        """The field to type into: for text=..., a field whose placeholder or label says it comes before any visible text."""
        t = str(target or "").strip()
        if t.startswith("text="):
            for loc in (self.page.get_by_placeholder(t[5:], exact=False).first, self.page.get_by_label(t[5:], exact=False).first):
                if loc.count() > 0:
                    return loc
        return self.locate(target)

    def locate(self, target):
        """#N (a number of inspect), css=..., text=..., or a plain CSS selector."""
        t = str(target or "").strip()
        if not t:
            raise ValueError("no target")
        if t.startswith("#") and t[1:].isdigit():
            n = int(t[1:])
            e = next((x for x in self.els if x["n"] == n), None)
            if not e:
                raise ValueError(f"there is no element {t} in elements.json")
            loc = self.page.locator(e["selector"]).first
            if loc.count() == 0 and e.get("text"):
                loc = self.page.get_by_text(e["text"], exact=False).first
            return loc
        if t.startswith("text="):
            return self.page.get_by_text(t[5:], exact=False).first
        if t.startswith("css="):
            t = t[4:]
        return self.page.locator(t).first

    def box(self, loc) -> list:
        b = loc.bounding_box()
        if not b:
            raise ValueError("the element is not visible")
        return [b["x"], b["y"], b["width"], b["height"]]

    def scroll_to(self, y: float, seconds: float) -> None:
        pg = self.page
        y0 = pg.evaluate("() => { document.documentElement.style.scrollBehavior = 'auto'; return window.scrollY; }")
        top = pg.evaluate("() => document.documentElement.scrollHeight - innerHeight")
        y1 = max(0.0, min(float(top), float(y)))
        if abs(y1 - y0) < 2:
            return
        self.stepped(lambda p: pg.evaluate("y => window.scrollTo(0, y)", y0 + (y1 - y0) * ease(p)), seconds)

    def into_view(self, loc, seconds: float = 0.9) -> list:
        """Scrolls (stepped, eased) until the element sits in the middle band, then returns its box in viewport pixels."""
        b = self.box(loc)
        vh = self.page.viewport_size["height"]
        if b[1] < vh * 0.12 or b[1] + b[3] > vh * 0.88:
            self.scroll_to(self.page.evaluate("() => window.scrollY") + b[1] - vh * 0.4, seconds)
            b = self.box(loc)
        return b

    def cursor_to(self, b: list, seconds: float = 0.7) -> tuple:
        x1, y1 = b[0] + b[2] / 2, b[1] + b[3] / 2
        x0, y0 = self.cur
        pg = self.page
        self.stepped(lambda p: pg.evaluate("([x, y]) => window.__dc.place(x, y)", [x0 + (x1 - x0) * ease(p), y0 + (y1 - y0) * ease(p)]), seconds)
        self.cur = (x1, y1)
        return x1, y1

    def place(self, x: float, y: float) -> None:
        self.page.evaluate("([x, y]) => window.__dc.place(x, y)", [x, y])
        self.cur = (x, y)

    def fence(self, loc) -> None:
        kind = loc.evaluate("e => (e.getAttribute('type') || '').toLowerCase() + '|' + (e.getAttribute('autocomplete') || '').toLowerCase()")
        if kind.startswith("password") or "cc-" in kind or "password" in kind:
            raise ValueError("the target is a password or payment field: a demo never types or clicks there")

    def settle(self, seconds: float) -> None:
        self.page.wait_for_timeout(int(seconds * 1000))

    def step(self, s: dict) -> dict:
        do = s.get("do")
        pg = self.page
        rec = {"do": do, "t0": self.now(), "step": s}
        if do == "goto":
            pg.goto(s["url"], wait_until="load", timeout=60000)
            self.settle(float(s.get("settle", 1.0)))
            vw, vh = pg.viewport_size["width"], pg.viewport_size["height"]
            self.place(vw * 0.5, vh * 0.62)
        elif do == "wait":
            self.settle(float(s.get("seconds", 1)))
        elif do in ("click", "hover"):
            loc = self.locate(s["target"])
            self.fence(loc)
            b = self.into_view(loc)
            x, y = self.cursor_to(b, float(s.get("move_s", 0.7)))
            rec["box"] = b
            pg.mouse.move(x, y)
            if do == "click":
                pg.evaluate("([x, y]) => window.__dc.ripple(x, y)", [x, y])
                pg.mouse.click(x, y)
                try:
                    pg.wait_for_load_state("load", timeout=8000)
                except Exception:
                    pass
                self.settle(float(s.get("settle", 0.9)))
                self.place(x, y)
            else:
                self.settle(float(s.get("settle", 0.8)))
        elif do == "type":
            loc = self.field(s["target"])
            self.fence(loc)
            b = self.into_view(loc)
            x, y = self.cursor_to(b, float(s.get("move_s", 0.6)))
            rec["box"] = b
            pg.mouse.click(x, y)
            text = str(s.get("text", ""))
            per = max(0.02, float(s.get("delay_ms", 70)) / 1000.0)
            self.live = False
            real0, v0 = time.time(), self.now()
            self.add(pg.screenshot(type="jpeg", quality=88), v0)
            for k, ch in enumerate(text, 1):
                pg.keyboard.type(ch)
                self.add(pg.screenshot(type="jpeg", quality=88), v0 + k * per)
            self.offset += (time.time() - real0) - per * len(text)
            self.floor = v0 + per * len(text) + 0.001
            self.live = True
            got = pg.evaluate("() => { const e = document.activeElement; return e ? (e.value !== undefined ? e.value : e.innerText || '') : ''; }")
            if text.strip() and text.strip()[-4:] not in str(got):
                raise ValueError("the text did not land in a field (the target is not a text field): use the field's number from inspect")
            self.settle(float(s.get("settle", 0.5)))
        elif do == "press":
            focused = pg.evaluate("() => { const e = document.activeElement; return e ? (e.getAttribute('type') || '').toLowerCase() : ''; }")
            if focused == "password":
                raise ValueError("Enter in a password field is never pressed in a demo")
            pg.keyboard.press(str(s.get("key", "Enter")))
            try:
                pg.wait_for_load_state("load", timeout=8000)
            except Exception:
                pass
            self.settle(float(s.get("settle", 0.8)))
        elif do == "scroll":
            to = s.get("to", "bottom")
            if isinstance(to, (int, float)):
                y = float(to)
            elif to == "bottom":
                y = 10 ** 7
            elif to == "top":
                y = 0.0
            else:
                b = self.box(self.locate(to))
                y = pg.evaluate("() => window.scrollY") + b[1] - pg.viewport_size["height"] * float(s.get("at", 0.25))
            self.scroll_to(y, float(s.get("seconds", 1.4)))
            self.settle(float(s.get("settle", 0.3)))
        elif do in ("zoom", "highlight"):
            if s.get("target"):
                loc = self.locate(s["target"])
                b = self.into_view(loc) if s.get("scroll", True) else self.box(loc)
                rec["box"] = b
                if do == "highlight" and s.get("cursor", True):
                    self.cursor_to(b, 0.6)
            self.settle(float(s.get("seconds", 2.0)))
        elif do == "caption":
            pass   # shown by the render from this moment for its seconds, while the next steps run
        else:
            raise ValueError(f"unknown step {do!r}")
        rec["t1"] = self.now()
        return rec


def cmd_record(a) -> int:
    sync_playwright = need_playwright()
    tour = json.load(open(a.tour, encoding="utf-8"))
    base = os.path.dirname(os.path.abspath(a.tour))
    fmt = tour.get("format", "landscape")
    if fmt not in FORMATS:
        raise SystemExit(f"format must be one of {', '.join(FORMATS)}")
    vw, vh, scale = FORMATS[fmt]
    els = []
    if tour.get("elements"):
        ep = tour["elements"] if os.path.isabs(tour["elements"]) else os.path.join(base, tour["elements"])
        els = json.load(open(ep, encoding="utf-8"))
    out = os.path.abspath(a.out)
    fdir = os.path.join(out, "frames")
    shutil.rmtree(fdir, ignore_errors=True)
    os.makedirs(fdir)
    log = []
    with sync_playwright() as pw:
        # the screencast draws at the browser's own scale: device_scale_factor alone gives 1x frames, so the browser is forced to it too
        br = pw.chromium.launch(headless=not a.headed, args=[f"--force-device-scale-factor={scale:g}"])
        ctx = br.new_context(viewport={"width": vw, "height": vh}, device_scale_factor=scale, locale="en-US")
        ctx.add_init_script(CURSOR_JS)
        pg = ctx.new_page()
        pg.goto(tour["url"], wait_until="load", timeout=60000)
        pg.wait_for_timeout(int(float(tour.get("settle", 1.5)) * 1000))
        player = Player(pg, els, fdir)
        player.place(vw * 0.5, vh * 0.62)
        t_start = player.now()
        player.add(pg.screenshot(type="jpeg", quality=88), t_start)
        player.live = True
        pg.screencast.start(fps=FPS, quality=88, size={"width": int(vw * scale), "height": int(vh * scale)}, on_frame=player.on_frame)
        player.settle(float(tour.get("lead_in", 0.6)))
        for i, s in enumerate(tour.get("steps") or []):
            try:
                rec = player.step(s)
                rec["ok"] = True
            except Exception as exc:
                player.live = True
                rec = {"do": s.get("do"), "t0": player.now(), "t1": player.now(), "step": s, "ok": False, "error": str(exc).splitlines()[0][:200]}
                say(f"  step {i + 1} ({s.get('do')}) failed: {rec['error']}")
            rec["i"] = i
            log.append(rec)
        player.settle(float(tour.get("tail", 1.0)))
        t_end = player.now()
        pg.screencast.stop()
        br.close()
    frames = sorted(player.frames, key=lambda f: f["t"])
    for f in frames:
        f["t"] = round(f["t"] - t_start, 4)
    for r in log:
        r["t0"], r["t1"] = round(r["t0"] - t_start, 3), round(r["t1"] - t_start, 3)
    duration = round(t_end - t_start, 3)
    write_json(os.path.join(out, "frames.json"), {"frames": frames, "scale": scale, "viewport": [vw, vh], "duration": duration})
    write_json(os.path.join(out, "log.json"), log)
    shutil.copyfile(a.tour, os.path.join(out, "tour.json"))
    bad = [r for r in log if not r["ok"]]
    say(f"recorded {duration:.1f} s, {len(frames)} frames, {len(log)} steps ({len(bad)} failed)")
    a.out = out
    return render(a)


# ---------------------------------------------------------------- render

def ease(p: float) -> float:
    p = min(max(p, 0.0), 1.0)
    return p * p * (3 - 2 * p)


def zoom_at(t: float, zooms: list) -> tuple:
    """(zoom factor, centre x, centre y in frame pixels) at time t: eased in over 0.45 s, held, eased out over 0.45 s."""
    best = (1.0, None, None)
    for z in zooms:
        a, b = z["t0"], z["t1"]
        if a - 0.01 <= t <= b + 0.45:
            k = ease((t - a) / 0.45) if t < a + 0.45 else (1.0 if t <= b else 1 - ease((t - b) / 0.45))
            f = 1 + (z["scale"] - 1) * k
            if f > best[0]:
                best = (f, z["cx"], z["cy"])
    return best


def render(a) -> int:
    from PIL import Image, ImageDraw
    out = os.path.abspath(a.out)
    fj = json.load(open(os.path.join(out, "frames.json"), encoding="utf-8"))
    log = json.load(open(os.path.join(out, "log.json"), encoding="utf-8"))
    tour = json.load(open(os.path.join(out, "tour.json"), encoding="utf-8"))
    frames, scale, dur = fj["frames"], float(fj["scale"]), float(fj["duration"])
    first = Image.open(os.path.join(out, "frames", frames[0]["file"]))
    W, H = first.size
    W, H = W - W % 2, H - H % 2
    times = [f["t"] for f in frames]
    zooms, rings, caps = [], [], []
    for r in log:
        s = r["step"]
        if not r.get("ok"):
            continue
        if r["do"] == "zoom" and r.get("box"):
            x, y, w, h = [v * scale for v in r["box"]]
            zooms.append({"t0": r["t0"], "t1": r["t1"], "scale": float(s.get("scale", 1.8)), "cx": x + w / 2, "cy": y + h / 2})
        if r["do"] == "highlight" and r.get("box"):
            rings.append({"t0": r["t0"], "t1": r["t1"], "box": [v * scale for v in r["box"]]})
        if r["do"] == "caption":
            caps.append({"t0": r["t0"], "t1": r["t0"] + float(s.get("seconds", 2.5)), "text": str(s.get("text", ""))})
    card = tour.get("title_card")
    card_s = float(card.get("seconds", 2.0)) if card else 0.0
    total = card_s + dur
    fsize = max(24, int(H * 0.05))
    fcap, ftitle, fsub = font(fsize), font(int(H * 0.085)), font(int(H * 0.04))
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", os.path.join(out, "demo.mp4")]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    cache = {"i": -1, "img": None}
    n_out = int(round(total * FPS))
    keys = {}
    key_times = {round(card_s + (r["t0"] + r["t1"]) / 2, 2): f"{r['i'] + 1} {r['do']}" for r in log if r.get("ok") and r["do"] != "caption"}
    for k in range(n_out):
        t = k / FPS
        if t < card_s:
            img = title_frame(first, card, W, H, ftitle, fsub, min(1.0, t / 0.3), 1 - ease((t - (card_s - 0.3)) / 0.3) if t > card_s - 0.3 else 1.0)
        else:
            ts = t - card_s
            i = max(0, bisect.bisect_right(times, ts) - 1)
            if i != cache["i"]:
                cache["img"] = Image.open(os.path.join(out, "frames", frames[i]["file"])).convert("RGB").crop((0, 0, W, H))
                cache["i"] = i
            img = cache["img"]
            z, cx, cy = zoom_at(ts, zooms)
            if z > 1.001:
                cw, ch = W / z, H / z
                x0 = min(max(cx - cw / 2, 0), W - cw)
                y0 = min(max(cy - ch / 2, 0), H - ch)
                img = img.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch))).resize((W, H), Image.LANCZOS)
            else:
                z, x0, y0 = 1.0, 0.0, 0.0
                img = img.copy()
            d = ImageDraw.Draw(img, "RGBA")
            for rg in rings:
                if rg["t0"] <= ts <= rg["t1"] + 0.2:
                    p = ease((ts - rg["t0"]) / 0.25)
                    bx, by, bw, bh = rg["box"]
                    pad = 10 * scale
                    xa, ya = (bx - pad - x0) * z, (by - pad - y0) * z
                    xb, yb = (bx + bw + pad - x0) * z, (by + bh + pad - y0) * z
                    d.rounded_rectangle([xa, ya, xb, yb], radius=int(14 * scale), outline=ACCENT + (int(255 * p),), width=max(4, int(4 * scale)))
            for c in caps:
                if c["t0"] <= ts <= c["t1"]:
                    alpha = min(1.0, (ts - c["t0"]) / 0.2, (c["t1"] - ts) / 0.2)
                    draw_caption(d, c["text"], W, H, fcap, alpha)
        for kt in list(key_times):
            if abs(kt - t) < 0.5 / FPS and len(keys) < 15:
                keys[kt] = (img.copy(), key_times.pop(kt))
        proc.stdin.write(img.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit("ffmpeg failed to encode the video")
    key_sheet(keys, out)
    say(f"the video: {os.path.normpath(os.path.join(out, 'demo.mp4'))} ({total:.1f} s, {W}x{H})")
    if a.gif:
        gif = os.path.join(out, "demo.gif")
        gw = 720 if W >= H else 400
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", os.path.join(out, "demo.mp4"), "-vf",
                        f"fps=12,scale={gw}:-2:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
                        gif], check=True)
        say(f"the GIF: {os.path.normpath(gif)} ({os.path.getsize(gif) // 1024} KB)")
    say(f"look at every step before you call it done: {os.path.normpath(os.path.join(out, 'keys.jpg'))}")
    return 1 if any(not r.get("ok") for r in log) else 0


def draw_caption(d, text: str, W: int, H: int, f, alpha: float) -> None:
    lines, cur = [], ""
    for w in text.split():
        trial = (cur + " " + w).strip()
        if d.textlength(trial, font=f) > W * 0.8 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    lh = int(f.size * 1.3)
    bw = max(d.textlength(x, font=f) for x in lines) + f.size * 1.4
    bh = lh * len(lines) + f.size * 0.8
    x0, y0 = (W - bw) / 2, H - bh - H * 0.07
    a = int(255 * max(0.0, min(1.0, alpha)))
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=int(f.size * 0.5), fill=(10, 10, 12, int(a * 0.88)))
    for i, ln in enumerate(lines):
        tw = d.textlength(ln, font=f)
        d.text(((W - tw) / 2, y0 + f.size * 0.4 + i * lh), ln, font=f, fill=(255, 255, 255, a))


def title_frame(first, card: dict, W: int, H: int, ftitle, fsub, fade_in: float, fade_out: float):
    from PIL import Image, ImageDraw, ImageFilter
    bg = first.convert("RGB").crop((0, 0, W, H)).filter(ImageFilter.GaussianBlur(radius=max(8, W // 80)))
    dark = Image.new("RGB", (W, H), (10, 10, 12))
    img = Image.blend(bg, dark, 0.62)
    d = ImageDraw.Draw(img, "RGBA")
    a = int(255 * max(0.0, min(fade_in, fade_out)))
    title = str(card.get("text", ""))
    sub = str(card.get("subtitle", ""))
    lines, cur = [], ""
    for w in title.split():
        trial = (cur + " " + w).strip()
        if d.textlength(trial, font=ftitle) > W * 0.84 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    lh = int(ftitle.size * 1.12)
    y = H / 2 - lh * len(lines) / 2 - (fsub.size if sub else 0)
    for ln in lines:
        tw = d.textlength(ln, font=ftitle)
        d.text(((W - tw) / 2, y), ln, font=ftitle, fill=(255, 255, 255, a))
        y += lh
    if sub:
        tw = d.textlength(sub, font=fsub)
        d.text(((W - tw) / 2, y + fsub.size * 0.5), sub, font=fsub, fill=(200, 200, 200, a))
    bw = W * 0.12
    d.rectangle([(W - bw) / 2, y + fsub.size * (2.2 if sub else 0.6), (W + bw) / 2, y + fsub.size * (2.2 if sub else 0.6) + max(6, H // 120)], fill=ACCENT + (a,))
    return img


def key_sheet(keys: dict, out: str) -> None:
    from PIL import Image, ImageDraw
    if not keys:
        return
    items = sorted(keys.items())
    tiles = []
    f = font(22)
    for t, (img, label) in items:
        th = img.copy()
        th.thumbnail((480, 480))
        d = ImageDraw.Draw(th)
        d.rectangle([0, 0, th.width, 32], fill=(0, 0, 0))
        d.text((6, 3), f"{t:.1f} s  step {label}", font=f, fill=(255, 220, 0))
        tiles.append(th)
    tw, thh = max(t.width for t in tiles), max(t.height for t in tiles)
    cols = 3 if tw >= thh else 5
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (tw + 8) + 8, rows * (thh + 8) + 8), (28, 28, 30))
    for i, t in enumerate(tiles):
        sheet.paste(t, (8 + (i % cols) * (tw + 8), 8 + (i // cols) * (thh + 8)))
    sheet.save(os.path.join(out, "keys.jpg"), quality=86)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", newline="\n")
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is not on PATH: install it (winget install ffmpeg, brew install ffmpeg)")
    ap = argparse.ArgumentParser(description="A polished demo video of a website, made by code.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("inspect")
    i.add_argument("url")
    i.add_argument("work")
    i.add_argument("--format", default="landscape", choices=list(FORMATS))
    r = sub.add_parser("record")
    r.add_argument("tour")
    r.add_argument("out")
    r.add_argument("--gif", action="store_true")
    r.add_argument("--headed", action="store_true", help="show the browser while it records")
    re_ = sub.add_parser("render")
    re_.add_argument("out")
    re_.add_argument("--gif", action="store_true")
    a = ap.parse_args()
    return {"inspect": cmd_inspect, "record": cmd_record, "render": render}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
