"""Builds the live demo (GitHub Pages) into _site/: the demo previews with the kit, each one's review sheet and a
thumbnail, the tour video, and index.html. Pages has no serve.py, so the previews' Save copies the JSON instead.
Needs Chrome or Edge and Pillow (for the sheets). The Pages workflow runs it; to look at the result locally:

    python docs/demo/build_site.py
    python -m http.server -d _site 8000        # http://127.0.0.1:8000/
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[2]
DEMO, SITE, KIT = REPO / "docs/demo", REPO / "_site", REPO / "skills/ui-preview/assets/kit"
PAGES = ["hud", "pause", "dialogue", "transition"]

shutil.rmtree(SITE, ignore_errors=True)
SITE.mkdir()
for name in ["index.html", "scene.js", "demo.mp4"]:
    shutil.copy(DEMO / name, SITE)
(SITE / "kit").mkdir()
for name in ["kit.js", "kit.css", "project.css"]:
    shutil.copy(KIT / name, SITE / "kit")
for page in PAGES:
    shutil.copytree(DEMO / page, SITE / page)
    # The site root stands in for a project's docs/mockups/.
    subprocess.run([sys.executable, str(KIT / "shots.py"), page, "--mockups", "."], cwd=SITE, check=True)
    first = json.loads((SITE / page / "manifest.json").read_text(encoding="utf-8"))["states"][0]["id"]
    with Image.open(SITE / page / "shots" / f"a_{first}.png") as shot:
        shot.convert("RGB").resize((640, 360), Image.Resampling.LANCZOS).save(SITE / page / "thumb.png")
    shutil.rmtree(SITE / page / "shots")
print("built", SITE)
