# Kit reference

## Files

| File | What it is | Edit it? |
|---|---|---|
| `kit.js` | Stage, tuning panel, states, variants, saving, shot mode | no |
| `kit.css` | The page's layout and panel look | no |
| `project.css` | The game's fonts (`@font-face`) and the panel palette (`--display`, `--bg`, `--panel`, `--panel-deep`, `--border`, `--text`, `--dim`, `--accent`) | yes, once |
| `serve.py` | Serves the project root and accepts saves | no |
| `shots.py` | Review sheet | no |
| `test_serve.py` | Regression check for `serve.py`'s security rules | no |
| `test_apply_godot.py` | Regression check for `apply_godot.py`'s shader groups | no |
| `godot_theme.js`, `apply_godot.py` | Godot reader and applier | no |
| `unity_theme.js`, `apply_uss.py` | Unity reader and USS applier | no |
| `unreal_theme.js` | Unreal DataTable reader | no |

## A page

```html
<link rel="stylesheet" href="../kit/kit.css">
<script src="../kit/kit.js"></script>
<script>
Kit.start({
  feature: "health_bar",
  fonts: ['16px "Body Font"'],          // optional: wait for these; declared fonts are loaded anyway
  images: { backdrop: "img/backdrop.png", icon: "../../../art/heart.png" },
  groups: {
    HealthBar: { note: "ui/HealthBar exports", params: {
      SegmentWidth: { value: 24, min: 8, max: 64, step: 4, unit: "px", hint: "one cell" },
      Style: { value: "flat", options: ["flat", "bevel"] },
    } },
    "theme: HealthBar": { params: { fill: { value: "#23db92ff" } } },
    Preview: { preview: true, params: { ReduceFlashing: { value: false } } },
  },
  variants: { a: {}, b: { "HealthBar.SegmentWidth": 16 } },
  draw(ctx, v, s) { /* paint one frame from v (values) and s = { state, variant, t, images } */ },
});
</script>
```

- **Spec kinds:** `{ value: number, min, max, step, unit? }` slider · `{ value: "#rrggbbaa" }` colour + alpha · `{ value: bool }` checkbox · `{ value, options }` dropdown. A slider also gets a box to type an exact value. Any spec may carry `hint` (tooltip) and `section`.
- **Groups** are named for where the values live in the engine; `preview: true` groups only drive the page and are left out of the JSON. Group names may contain dots (variant paths split on the last dot).
- **The panel:** each group folds open and shut, and so does each **section** inside it: a spec's `section: "Energy"`, or the part before a slash in its key (`panel/bg_color` sits in section `panel`). Use sections when a group has more than about six values. Hovering a value, section or group dims the stage and outlines each part it changes (the kit redraws the frame with those values pushed far off and compares). That needs nothing from the page, so keep `draw` pure; a value with no visible effect in the current state says so. Clicking the stage does the reverse: it marks the values that change the pixels around the click. Holding Space (or the Compare button) shows the saved values instead of the tuning, and Z (or the zoom button) steps fit / 1:1 / 2x, toward the pointer.
- **Variants** in the config must match `manifest.json`'s `variants`; a mismatch warns in the console.
- **`Kit.spec(value, unit?)`** turns a raw value from a project file into a spec (colour, checkbox, a slider sized around the value, or a one-option dropdown for other strings). The engine readers use it.
- **Captions** show on the review sheet cut to about 70 characters with the state id; keep them short.
- **`manifest.json`:** `{ "title", "stage": [w, h], "states": [{ "id", "caption", "shotTime" }], "variants": { "a": { "name", "note" } }, "recommend": { "variant", "why" } }`.

## Saving and values

| File | Written by | Meaning |
|---|---|---|
| `values.draft.json` | every change, ~0.4 s after it (needs `serve.py`) | what's on screen now; never the spec |
| `values.json` | Save / Ctrl+S, or you from a pasted JSON | the approved spec; the page opens on it |
| localStorage | every change; Save without `serve.py` | per browser; a stored value only applies while its default hasn't changed. Without `serve.py`, Save keeps the values here as the page's defaults |

Format: `{ "feature", "variant", "values": { Group: { Key: value } } }` (drafts add `"draft": true`). Colours are `#rrggbbaa`.

## `serve.py`

`python docs/mockups/kit/serve.py [--port 8765] [--root .] [--mockups docs/mockups]`

- Binds 127.0.0.1 only. Refuses any request whose `Host` isn't `localhost:<port>` / `127.0.0.1:<port>` (DNS rebinding), and any save whose `Origin` isn't this server or that isn't `application/json` (other websites can't write).
- A save is `POST /__save` with `Content-Type: application/json` and the body `{ "path": "/<mockups>/<feature>/values.json", "data": { … } }` (the page's own URL path; `values.draft.json` for drafts).
- Writes only `values.json` / `values.draft.json`, directly inside `<root>/<mockups>/<feature>/` where a `manifest.json` exists, atomically, at most 1 MB. No directory listings.
- A GET for one of those two files that isn't saved yet answers `204 No Content` (no console 404 on a page's first load); any other missing file is a 404.
- `python docs/mockups/kit/test_serve.py` checks all of that (exit code = failed checks).

## `shots.py`

`python docs/mockups/kit/shots.py <feature> [--variant b ...] [--defaults] [--mockups docs/mockups]`

- Opens every state of every variant in headless Chrome/Edge/Chromium at the manifest's `stage`, saves `shots/<variant>_<state>.png`, stitches `sheet.png` (`sheet_<variants>.png` with `--variant`).
- Uses `values.json` for its variant; `--defaults` shoots the page's defaults.
- Exits non-zero if a page fails; the failing shot shows the error. Set `CHROME=<path>` to pick a browser.
- Shot-mode URL: `?shot=1&v=<variant>&s=<state>[&t=<seconds>][&defaults=1]`; the page title becomes `kit:ok` or `kit:error <message>`.
