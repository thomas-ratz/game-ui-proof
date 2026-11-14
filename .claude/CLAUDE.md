# game-ui-proof: working notes

An open-source (MIT) Claude Code plugin with one skill, `ui-preview`: the agent builds a tunable HTML preview of a game's UI over a real screenshot, the human tunes and presses Save, and the saved `values.json` is applied to the engine. Pitch and positioning are in `README.md`.

## Layout
- `.claude-plugin/plugin.json` (name, version: bump on every release) and `marketplace.json` (this repo is its own marketplace).
- `skills/ui-preview/SKILL.md`: the workflow the agent follows. Keep it lean; detail goes in `references/kit.md` (page format, saving, `serve.py`, `shots.py`) and `references/engines.md` (Godot, Unity, Unreal, web).
- `skills/ui-preview/assets/kit/`: what users copy into their project (`docs/mockups/kit/`). `project.css` is the only file a user edits. `godot_theme.js` + `apply_godot.py`, `unity_theme.js` + `apply_uss.py`, `unreal_theme.js` are per engine.
- `skills/ui-preview/assets/{template,godot,unity,unreal}/`: example pages. `assets/godot/game_shots.gd`: backdrop screenshot template.
- `docs/demo/`: neutral demo previews (`hud/`, `pause/`, `dialogue/`, `transition/`, sharing the procedural level in `scene.js`; no game's art), the README tour `demo.gif`/`demo.mp4`, and `record.py`, which re-records it (`python docs/demo/record.py`). `build_site.py` builds the GitHub Pages demo into `_site/` (index, previews, review sheets).
- `examples/{godot,unity,unreal}/`: fake projects the example pages read and the appliers write; `python examples/setup.py` copies the kit and pages into their `docs/mockups/` (git-ignored).
- `.github/workflows/`: `ci.yml` (the checks below on Python 3.8 and 3.13), `pages.yml` (the demo site, on push to main).
- `docs/launch.md`: launch kit (submission drafts, venue checklist).

## Rules
- Game-agnostic: no project names, palettes, fonts, key bindings or paths from any one game in the skill. Examples use neutral colours.
- Stdlib-only Python ≥ 3.8 (Pillow only for `shots.py`), plain browser JS (no build step, no modules, one global per file), no new dependencies.
- `serve.py` is a security boundary: Host check (DNS rebinding), Origin + JSON content-type check (cross-site writes), writes only `values.json` / `values.draft.json` inside `<root>/<mockups>/<feature>/` with a `manifest.json`. Any change to it keeps `assets/kit/test_serve.py` passing.
- The appliers reject group and key names that aren't plain identifiers and are dry-run by default. Keep it that way.
- Docs match the code: when an API changes, update `SKILL.md`, `references/*.md`, the example pages and `CHANGELOG.md` in the same change.
- Never commit or push unless asked.

## Checks before a release
- `python skills/ui-preview/assets/kit/test_serve.py` and `test_apply_godot.py` (exit code = failed checks).
- `python -m py_compile` on every `.py`, `node --check` on every `.js`.
- Render the example pages: `python examples/setup.py`, then `python docs/mockups/kit/shots.py <feature>` from each sample project (CI does this and uploads the sheets); look at each `sheet.png`.
- Render the demo: `python docs/demo/build_site.py`, then look at `_site/`.
- `claude plugin validate --strict .` and `claude plugin validate --strict .claude-plugin/plugin.json` (this file lives in `.claude/` because a `CLAUDE.md` at the plugin root fails the second).
- A blind trial: a fresh agent that reads only `skills/ui-preview/` builds a preview for a fake project at a non-1920 resolution and logs every friction point.
