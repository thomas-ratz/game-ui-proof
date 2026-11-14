---
name: ui-preview
description: In a game project, build a tunable HTML preview of a HUD element, menu, prompt, transition or screen effect before implementing it in the engine, and turn the values the person tunes into the build spec. The preview is drawn at the game's resolution over a real game screenshot, with a tuning panel (sliders, colours, variants, states), live saving to disk, a Save button that writes the approved values.json, a review sheet of every state, and scripts that write the approved values into Godot or Unity. Use when someone working on a game asks to design, mock up, restyle or tweak how its UI or a visual effect looks or moves, or asks for a preview or mockup they can tune, even for a small change.
argument-hint: "[feature, e.g. 'health bar', 'pause menu', 'level-up flash']"
---

# UI preview

Nothing that changes how the game's UI looks is built until the person has tuned an HTML preview of it and pressed Save. The saved `values.json` is the spec: every number in it becomes an editor-exposed property or theme entry, never a magic number in code. A change nobody can see needs no preview.

**Order of work:** what to preview → a screenshot of that spot → the preview page → the review sheet → they tune and press Save → build from `values.json` → build-vs-preview sheet.

## 1. Set up (once per project)

- Copy `assets/kit/` to `docs/mockups/kit/` (another folder works: pass `--mockups` to the scripts). Engine-specific files can be left out when unused: `godot_theme.js` + `apply_godot.py` (Godot), `unity_theme.js` + `apply_uss.py` (Unity), `unreal_theme.js` (Unreal). Godot: also copy `assets/godot/project.js` into `kit/` and fill it in (fonts, key glyphs); the Godot pages load it from there.
- `project.css` is the only kit file to edit: the game's fonts (`@font-face`) and the panel palette, including `--display`. kit.js loads every declared font before drawing.
- Keep the previews out of the engine's import (Godot: an empty `.gdignore` in `docs/mockups/`) and add `docs/mockups/*/values.draft.json` and `docs/mockups/*/shots/` to `.gitignore`.
- Serve the project root: `python docs/mockups/kit/serve.py` (stdlib only), then open `http://127.0.0.1:8765/docs/mockups/<feature>/`. Pages load the game's art by relative path and save their tuning to disk (§5).
- Reading the project's own styles into the panel: Godot `GodotTheme` (theme `.tres`), Unity `UnityTheme` (`.uss`, ScriptableObject `.asset`), Unreal `UnrealTheme` (DataTable exported to JSON/CSV). See `references/engines.md`; each has a working example page in `assets/<engine>/`.

## 2. Ask, then get the real backdrop

- Ask which screen, element or effect, and in what situation, unless that's already clear.
- Screenshot that spot at the game's viewport size (the project's resolution setting; also the manifest's `stage`) with the UI hidden, plus one with today's UI shown as the baseline. Use a small script the engine runs (Godot template: `assets/godot/game_shots.gd`; others: `references/engines.md`) and keep it next to the preview for the build check.
- Ask the person for a screenshot only when the spot can't be reached by script. For something new with nothing to shoot yet, or when the engine can't be run here, use a plain or mocked backdrop and say so in the state's caption.

## 3. Write the page

Copy `assets/template/` (or `assets/<engine>/`) to `docs/mockups/<feature>/`. The page format, panel specs, `Kit.spec` and URL parameters are in `references/kit.md`.

- **`manifest.json`:** title, `stage` ([w, h]), `states` (one per situation the player can see: empty, full, focused, disabled, longest text, mid-animation; each with a caption and `shotTime`), `variants` (2–4 when there's a real choice, each with a name and a note), `recommend` (variant and why, in a line or two).
- **`index.html`:** `Kit.start({ feature, images, groups, variants, draw })`. Give a group of more than about six values `section`s so the panel folds them. Each group is the place the values will live in the engine (a script class, a theme type, a shader), each key the property name the build will use, in the engine's units. `draw(ctx, values, s)` must be a pure function of `s.t` (loop animations with `t % length`).
- **The game's own look, not an approximation:** its fonts and sizes, theme colours (a new colour is a proposal: say which palette it joins), real art by relative path, real text and numbers, and prompts showing the keys actually bound.
- Pixel art: whole pixels, no smoothing (the kit's default).
- Motion runs at its real duration and easing. Anything that shakes, drifts, flashes or blinks gets Reduce Motion / Reduce Flashing toggles in a `preview: true` group, showing what those settings turn it into.
- When tuning something that exists, variant `a` redraws it exactly as it is today. Check it against the baseline screenshot until they match, or every other variant is compared against a wrong baseline.
- Something several previews draw goes in a shared file in the kit, not copied per page.

## 4. The review sheet

- `python docs/mockups/kit/shots.py <feature>` (needs Chrome, Edge or Chromium, and Pillow ≥ 10.1) writes `shots/<variant>_<state>.png` and stitches `sheet.png`. It uses the saved `values.json` for its variant (`--defaults` for the page's defaults) and exits non-zero if a page fails, with the error drawn on that shot.
- Look at the sheet before showing it; crop what's being decided at 2×: clipped or overlapping text, the wrong font, anything off the stage, an animation frozen at a dull moment (move its `shotTime`).
- Send the sheet, the live URL and the decisions to make, with your recommendation.

## 5. Reading the tuning

- **While they tune**, every change is written to `<feature>/values.draft.json`. Read it whenever they ask what you think; never build from it.
- **Save** (or Ctrl/Cmd+S) writes `<feature>/values.json`, the approved spec, and the page then opens on it: rows that differ are marked, ↺ puts one value back, Reset puts all back. Preview-only values are never marked or saved.
- Without `serve.py` the tuning lives only in the browser: Save copies the JSON (and keeps it as that browser's defaults), they paste it in the chat, and you save it as `values.json`.
- Format: `{"feature", "variant", "values": {Group: {Key: value}}}`; preview-only groups are left out.

## 6. Build from the spec

- **Godot:** `python docs/mockups/kit/apply_godot.py <feature>` lists what the spec changes in the theme `.tres` and in the `[Export]` / `@export` defaults of the script each group names, in the uniform defaults of a `<name>.gdshader` group, keys with no export yet, and scenes that override those properties. `--write` applies.
- **Unity:** `python docs/mockups/kit/apply_uss.py <feature>` does the same for USS custom properties (`uss:` groups). ScriptableObject and Unreal DataTable values are applied by hand or by re-importing the edited table.
- Build what doesn't exist yet: colours, fonts and panels in the engine's theme or style system; sizes, offsets, durations and strengths as editor-exposed properties grouped like the JSON, with the approved values as defaults.
- Verify in the running game: screenshot each state the preview has and make `<feature>/build_vs_preview.png`, game shot beside preview shot. Fix what differs. Say what wasn't checked; browser and engine text antialiasing differ, so judge position and size, not edge pixels.
- A later change to an approved look is a new round: preview, sheet, Save, build.

## Rules

- Previews stay in the repo: they record why the UI looks the way it does. Commit `sheet.png` and `values.json`; `shots/` and drafts are regenerated.
- No build before `values.json` exists; never build from the draft.
- If the kit lacks something a preview needs, add it to the kit, not to one page.
