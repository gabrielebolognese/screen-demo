"""The skill's self-test on a local page (tests/site.html, no network): inspect, then a tour with a caption, typing, a click, a highlight,
a scroll, a zoom and a hover, recorded and rendered with a GIF; then the password fence. About a minute.
    python tests/selftest.py [--keep]"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(SKILL, "scripts", "demo.py")


def run(*args, ok=(0,)):
    res = subprocess.run([sys.executable, DEMO, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode not in ok:
        raise SystemExit(f"FAIL: demo.py {args[0]} exited {res.returncode}:\n{res.stdout}\n{res.stderr}")
    return res.stdout


def main():
    tmp = tempfile.mkdtemp(prefix="screen-demo-test-")
    site = os.path.join(tmp, "site.html")
    shutil.copyfile(os.path.join(SKILL, "tests", "site.html"), site)
    html = open(site, encoding="utf-8").read().replace("</section>\n</body>", "</section>\n<form><input id=\"pw\" type=\"password\" placeholder=\"password\"></form>\n</body>")
    open(site, "w", encoding="utf-8").write(html)
    url = Path(site).resolve().as_uri()
    work = os.path.join(tmp, "work")
    out = run("inspect", url, work)
    els = json.load(open(os.path.join(work, "elements.json"), encoding="utf-8"))
    assert any(e["tag"] == "button" and "Make the note" in e["text"] for e in els), "inspect missed the button"
    assert os.path.isfile(os.path.join(work, "page-1.jpg")), "no slice"
    n = {e["text"]: e["n"] for e in els}
    tour = {"url": url, "format": "landscape", "elements": "elements.json", "title_card": {"text": "Self-test", "seconds": 1.0},
            "steps": [{"do": "caption", "text": "Type a thought", "seconds": 2.0},
                      {"do": "type", "target": f"#{n['Type a thought...']}", "text": "hello", "delay_ms": 60},
                      {"do": "click", "target": f"#{n['Make the note']}"},
                      {"do": "highlight", "target": "css=#done", "seconds": 1.0},
                      {"do": "scroll", "to": f"#{n['Start free']}", "seconds": 1.0},
                      {"do": "zoom", "target": f"#{n['Start free']}", "scale": 1.6, "seconds": 1.2},
                      {"do": "hover", "target": f"#{n['Start free']}"}]}
    tp = os.path.join(work, "tour.json")
    json.dump(tour, open(tp, "w", encoding="utf-8"))
    outdir = os.path.join(tmp, "out")
    run("record", tp, outdir, "--gif")
    log = json.load(open(os.path.join(outdir, "log.json"), encoding="utf-8"))
    assert all(r["ok"] for r in log), [r for r in log if not r["ok"]]
    for f in ("demo.mp4", "demo.gif", "keys.jpg"):
        assert os.path.isfile(os.path.join(outdir, f)), f"no {f}"
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height", "-of", "json", os.path.join(outdir, "demo.mp4")],
                           capture_output=True, text=True).stdout
    p = json.loads(probe)
    st = p["streams"][0]
    assert (st["width"], st["height"]) == (1920, 1080), (st["width"], st["height"])
    assert float(p["format"]["duration"]) > 6, p["format"]["duration"]
    fr = json.load(open(os.path.join(outdir, "frames.json"), encoding="utf-8"))["frames"]
    scroll = next(r for r in log if r["do"] == "scroll")
    k = sum(1 for f in fr if scroll["t0"] <= f["t"] <= scroll["t1"])
    assert k >= 20, f"the scroll has only {k} frames"
    # the fence: typing into a password field must fail the step, never type
    bad = dict(tour, steps=[{"do": "type", "target": "css=#pw", "text": "secret"}])
    json.dump(bad, open(tp, "w", encoding="utf-8"))
    run("record", tp, os.path.join(tmp, "out-bad"), ok=(1,))
    blog = json.load(open(os.path.join(tmp, "out-bad", "log.json"), encoding="utf-8"))
    assert not blog[0]["ok"] and "password" in blog[0]["error"], blog
    print(f"selftest OK: inspect, {len(log)} steps recorded ({k} frames in a 1 s scroll), video, GIF, the password fence "
          f"({tmp if '--keep' in sys.argv else 'cleaned up'})")
    if "--keep" not in sys.argv:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
