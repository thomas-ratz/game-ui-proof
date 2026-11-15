# Changelog

All notable changes to game-ui-proof. Versions follow [semver](https://semver.org); the version lives in `.claude-plugin/plugin.json`.

## Unreleased

- Unreal C++ class defaults: `UnrealTheme.loadClass(header, { className, categories, ini })` reads a header's UCLASS defaults (a `UDeveloperSettings` or any class) into one group per class, named without its U / A / F prefix: every editable UPROPERTY with a literal default, a section per Category, doc comments as hints, ClampMin / ClampMax / UIMin / UIMax as slider ranges, same-header enums as dropdowns, FLinearColor / FColor as colours, FVector2D / FVector / FIntPoint / FMargin members as `Prop/X`; a Config class's `Config/Default<Config>.ini` overrides replace the header defaults. `UnrealTheme.get(class, key)` reads them.
- `apply_unreal.py` writes a spec back: `Key=Value` in `[/Script/<Module>.<Class>]` of `Default<Config>.ini` (default; section created if missing, line endings kept), or `--target header` for the declaration's default. Lists keys with no UPROPERTY yet with a declaration to paste. Dry run by default; `test_apply_unreal.py` checks it.
- The Unreal example page and sample project use a settings class (`HudPanelSettings`) next to the DataTable; CI dry-runs the applier on it.

## 1.1.0 (2026-11-14)

- Godot shader uniforms: `GodotTheme.loadShader(resPath)` reads a `.gdshader`'s uniforms as a tuning group named after the file (source_color vec3/vec4 colours, hint_range sliders, bools, other defaults), read in `draw` with `GodotTheme.uniform(file, name)`; `apply_godot.py` writes a `"<name>.gdshader"` group back into that shader's uniform defaults and lists `.tscn` / `.tres` that set `shader_parameter/<name>`. `test_apply_godot.py` checks it.
- `serve.py` answers `204 No Content` for a `values.json` / `values.draft.json` not saved yet in a preview folder, so a page's first load logs no 404.
- `game_shots.gd`: loading the level is its own `load_level()`, for games that load levels through a service of their own.

## 1.0.0 (2026-11-14)

First public release.

- Tunable HTML previews for game UI: stage at the game's resolution, tuning panel (sliders, colours, checkboxes, dropdowns), states and variants, Reduce Motion / Reduce Flashing toggles.
- Saving: live drafts (`values.draft.json`), Save / Ctrl+S writes the approved `values.json`, which becomes the page's defaults; per-value revert; changed values marked.
- `serve.py`: local server that accepts saves only from its own pages, only into preview folders. `test_serve.py` checks its rules.
- `shots.py`: review sheet of every state and variant via headless Chrome/Edge/Chromium; uses the saved spec; fails loudly on page errors.
- Readers: Godot theme `.tres` (`GodotTheme`), Unity `.uss` and ScriptableObject `.asset` (`UnityTheme`), Unreal DataTable JSON/CSV export (`UnrealTheme`).
- Appliers: `apply_godot.py` (theme entries, StyleBoxes, C# / GDScript export defaults; reports scene overrides), `apply_uss.py` (USS custom properties). Both dry-run by default.
- Example pages: engine-agnostic template, Godot, Unity, Unreal; Godot screenshot script template.
- `examples/`: fake Godot, Unity and Unreal projects the example pages run in out of the box (`python examples/setup.py`).
- Live demo on GitHub Pages: four neutral previews (HUD, pause menu, dialogue, level-clear transition) with their review sheets, built by `docs/demo/build_site.py`.
- CI: `test_serve.py`, compile and parse checks on Python 3.8 and 3.13, example sheets rendered in the sample projects, applier dry runs.
- A page that fails before `Kit.start` (a reader that can't find its file) now shows its error, and `shots.py` reports it instead of "the page never finished".
- Tuning panel: groups and sections fold open and shut (remembered per browser); hovering a value, section or group dims the stage and outlines each part it changes; clicking the stage marks the values that change that spot; holding Space (or Compare) shows the saved values; Z (or the zoom button) steps fit / 1:1 / 2x; sliders get a box to type an exact value; colours show opacity as a percentage; Save and the save status stay pinned at the panel's foot; on a narrow screen (a phone) the stage sits above the panel.
- Save always makes the saved values the defaults: preview-only toggles are no longer marked as changed, and without `serve.py` Save copies the JSON and keeps it as this browser's defaults.
- Review-sheet captions over ~70 characters end in "..." instead of being cut silently.
