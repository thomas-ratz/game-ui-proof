"""Copies the kit and the example pages from skills/ui-preview/assets/ into each sample project's docs/mockups/, the
way the skill sets up a real project. Re-run after changing the kit or a page: it replaces docs/mockups/ each time,
saved values.json included.

    python examples/setup.py
    cd examples/godot
    python docs/mockups/kit/serve.py              # then open http://127.0.0.1:8765/docs/mockups/confirm_dialog/
    python docs/mockups/kit/shots.py confirm_dialog
"""
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "skills/ui-preview/assets"
PAGES = {  # sample project -> {feature folder: example page in assets/}
    "godot": {"confirm_dialog": "godot", "health_bar": "template"},
    "unity": {"hud_panel": "unity"},
    "unreal": {"hud_panel": "unreal"},
}
SKIP = shutil.ignore_patterns("__pycache__", "game_shots.gd", "project.js")

for project, pages in PAGES.items():
    mockups = HERE / project / "docs/mockups"
    shutil.rmtree(mockups, ignore_errors=True)
    shutil.copytree(ASSETS / "kit", mockups / "kit", ignore=SKIP)
    if project == "godot":
        shutil.copy(ASSETS / "godot/project.js", mockups / "kit")
        (mockups / ".gdignore").touch()  # keep the previews out of Godot's import
    for feature, page in pages.items():
        shutil.copytree(ASSETS / page, mockups / feature, ignore=SKIP)
    print(f"examples/{project}/docs/mockups: kit, {', '.join(pages)}")
