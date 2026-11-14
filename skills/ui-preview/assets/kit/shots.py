"""Screenshots every state of every variant of a UI preview and stitches a labelled review sheet.

    python docs/mockups/kit/shots.py hud            # all variants, run from the project root
    python docs/mockups/kit/shots.py hud --variant b                 # writes sheet_b.png
    python docs/mockups/kit/shots.py hud --defaults                  # the page's defaults, ignoring values.json
    python docs/mockups/kit/shots.py hud --mockups design/previews   # another folder

Writes <mockups>/<feature>/shots/<variant>_<state>.png and <mockups>/<feature>/sheet.png (sheet_<variants>.png with
--variant). A variant whose saved values.json is for it is shot with those values (the approved spec), the others
with their defaults. The stage size is the manifest's "stage" ([w, h], default 1920x1080). A page that fails shows
its error in its shot and makes the script exit non-zero. Serves the project root itself on a free local port, so no
server needs to be running. Needs Chrome or Edge (CHROME=<path> to pick one) and Pillow >= 10.1.
"""
import argparse
import functools
import html
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageDraw, ImageFont

ROOT = Path.cwd()
BROWSERS = [
    os.environ.get("CHROME", ""),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "chrome", "msedge",
]
THUMB_WIDTH = 640
LABEL_HEIGHT = 30
GAP = 12
BACKGROUND, TEXT, ACCENT = (24, 24, 27), (228, 228, 231), (94, 174, 255)


def browser():
    for candidate in BROWSERS:
        if candidate and (Path(candidate).is_file() or shutil.which(candidate)):
            return candidate
    sys.exit("No Chrome or Edge found; set CHROME to its path.")


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def shoot(chrome, url, out, stage):
    """Shoots the page and returns its error, or None. kit.js titles the page kit:ok or kit:error <message>."""
    # Headless Chrome's viewport is smaller than --window-size (16 px narrower on Windows, shorter everywhere):
    # shoot a window well past the stage on both axes and crop the stage out of its top-left corner.
    result = subprocess.run([
        chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
        f"--window-size={stage[0] + 200},{stage[1] + 400}", "--virtual-time-budget=5000",
        f"--screenshot={out}", "--dump-dom", url,
    ], check=True, capture_output=True, timeout=120, text=True, encoding="utf-8", errors="replace")
    with Image.open(out) as image:
        image.crop((0, 0, *stage)).save(out)
    title = re.search(r"<title>(.*?)</title>", result.stdout, re.S)
    title = html.unescape(title.group(1)) if title else ""
    if title == "kit:ok":
        return None
    return title[len("kit:error "):] if title.startswith("kit:error") else f"the page never finished (title: {title!r})"


def sheet(feature_dir, manifest, variants, stage, name):
    font = ImageFont.load_default(size=18)
    head = ImageFont.load_default(size=24)
    thumb = (THUMB_WIDTH, round(THUMB_WIDTH * stage[1] / stage[0]))
    cols, rows = len(variants), len(manifest["states"])
    width = cols * thumb[0] + (cols + 1) * GAP
    height = 50 + rows * (thumb[1] + LABEL_HEIGHT + GAP) + GAP
    page = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(page)
    for c, v in enumerate(variants):
        x = GAP + c * (thumb[0] + GAP)
        draw.text((x, 14), f"{v}  {manifest['variants'][v]['name']}", fill=ACCENT, font=head)
        for r, state in enumerate(manifest["states"]):
            y = 50 + r * (thumb[1] + LABEL_HEIGHT + GAP)
            label = f"{state['id']}: {state['caption']}"
            draw.text((x, y + 4), label if len(label) <= 72 else label[:69] + "...", fill=TEXT, font=font)
            with Image.open(feature_dir / "shots" / f"{v}_{state['id']}.png") as shot:
                page.paste(shot.convert("RGB").resize(thumb, Image.Resampling.LANCZOS), (x, y + LABEL_HEIGHT))
    page.save(feature_dir / name)
    return feature_dir / name


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("feature")
    parser.add_argument("--variant", action="append", help="only these variants (repeatable); writes sheet_<variants>.png")
    parser.add_argument("--mockups", default="docs/mockups", help="the previews folder, from the project root")
    parser.add_argument("--defaults", action="store_true", help="shoot the page's defaults, ignoring values.json")
    args = parser.parse_args()

    feature_dir = ROOT / args.mockups / args.feature
    manifest = json.loads((feature_dir / "manifest.json").read_text(encoding="utf-8"))
    variants = args.variant or list(manifest["variants"])
    unknown = [v for v in variants if v not in manifest["variants"]]
    if unknown:
        sys.exit(f"Not in manifest.json: {', '.join(unknown)}")
    stage = manifest.get("stage", [1920, 1080])
    (feature_dir / "shots").mkdir(exist_ok=True)

    chrome = browser()
    server = serve()
    errors = []
    page = quote(f"/{Path(args.mockups).as_posix().strip('/')}/{args.feature}/")
    try:
        for v in variants:
            for state in manifest["states"]:
                url = (f"http://127.0.0.1:{server.server_port}{page}?shot=1&v={quote(v)}&s={quote(state['id'])}"
                       + ("&defaults=1" if args.defaults else ""))
                out = feature_dir / "shots" / f"{v}_{state['id']}.png"
                # A busy machine occasionally drops one asset request; a real page error fails twice.
                error = shoot(chrome, url, out, stage) and shoot(chrome, url, out, stage)
                print(f"shot {v}_{state['id']}" + (f"  FAILED: {error}" if error else ""))
                if error:
                    errors.append(f"{v}_{state['id']}: {error}")
    finally:
        server.shutdown()
    print("sheet", sheet(feature_dir, manifest, variants, stage, f"sheet_{'_'.join(variants)}.png" if args.variant else "sheet.png"))
    if errors:
        sys.exit(f"{len(errors)} shot(s) failed:\n" + "\n".join(errors))


if __name__ == "__main__":
    main()
