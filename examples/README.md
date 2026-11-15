# Sample projects

Fake Godot, Unity and Unreal projects with just enough files for the example pages in `skills/ui-preview/assets/` to read, render and write back. No game, no art: the pages draw on a plain backdrop.

| Project | Files the pages read | Pages (`docs/mockups/…`) | Writes back with |
|---|---|---|---|
| `godot/` | `project.godot`, `ui/theme.tres`, `ui/ConfirmDialog.cs`, `ui/health_bar.gd` | `confirm_dialog` (Godot), `health_bar` (template) | `apply_godot.py` |
| `unity/` | `Assets/UI/Theme.uss`, `Assets/UI/HudStyle.asset` | `hud_panel` | `apply_uss.py` |
| `unreal/` | `Source/HudExample/UI/HudPanelSettings.h` + `Config/DefaultGame.ini` (a UDeveloperSettings), `Content/UI/DT_HudStyle.json` (a DataTable export) | `hud_panel` | `apply_unreal.py` (the class); the DataTable by hand |

```bash
python examples/setup.py
```

That copies the kit and the pages into each project's `docs/mockups/` (git-ignored, replaced on every run). Then, from a project folder:

```bash
python docs/mockups/kit/serve.py
```

Open `http://127.0.0.1:8765/docs/mockups/confirm_dialog/`, tune, press Save, then:

```bash
python docs/mockups/kit/apply_godot.py confirm_dialog
```

That's a dry run; `--write` edits the sample's files (`git checkout examples/` puts them back). `python docs/mockups/kit/shots.py confirm_dialog` renders the review sheet; CI renders all four.
