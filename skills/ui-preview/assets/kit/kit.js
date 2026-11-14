// Shared machinery for UI previews (the ui-preview skill). Copy to docs/mockups/kit/.
//
// A feature page calls Kit.start({ feature, images, groups, variants, draw }) and keeps a manifest.json beside it:
//   { "title", "stage": [w, h], "states": [{ "id", "caption", "shotTime" }], "variants": { "a": { "name", "note" } },
//     "recommend": { "variant", "why" } }
// groups: { GroupName: { note?, preview?, params: { Name: spec } } }, where a spec is
//   { value: number, min, max, step, unit? }   slider
//   { value: "#rrggbbaa" }                     colour picker + alpha
//   { value: true|false }                      checkbox
//   { value, options: [...] }                  dropdown
// and may carry hint (tooltip) and section (a collapsible sub-heading inside its group; a key with a slash, like
// "panel/bg_color", is put in section "panel" by itself). GroupName is where the value will live in the engine (a
// script, a shader, a theme type); a group with preview: true only drives the page and is left out of the JSON.
// Groups and sections fold open and shut (remembered per browser). Hovering a value, a section or a group dims the
// stage and outlines what it changes: the frame is drawn again with those values pushed far off and compared.
// Clicking the stage does the reverse: it marks the values that change the pixels around the click. Holding Space (or
// the Compare button) shows the saved values instead of the tuning; Z (or the zoom button) steps fit / 1:1 / 2x.
// Kit.spec(value, unit?) turns a raw value read from a project file into a spec: a colour, a checkbox, a slider
// sized around the value (unit "px" etc. widens it), or a one-option dropdown for any other string.
// variants: { a: { "Group.Name": value, ... } }: each variant's overrides over the specs' values (split on the last
// dot, so group names may contain dots). Its keys must match the manifest's variants.
// Optional in the config: fonts: ['16px "My Font"', ...] to wait for. The stage is the manifest's "stage"
// (default 1920x1080, the game viewport).
// Saving: served by serve.py, every change is written to <feature>/values.draft.json and Save (or Ctrl/Cmd+S) writes
// values.json, the approved spec, which then becomes the page's defaults (a row that differs from it is marked, with a
// revert button; preview-only rows are never marked). Without serve.py the tuning lives in localStorage, Save copies
// the JSON and keeps it as this browser's defaults, and Copy / Paste JSON carry it.
// draw(ctx, values, s) paints one frame on the stage canvas; s = { state, variant, t, images }. t is seconds
// since the state was shown (frozen at the state's shotTime in screenshot mode), so draw is a pure function of it.
// Screenshot mode (?shot=1, used by shots.py) draws once with values.json when it is for the variant shot (&defaults=1
// to skip it), then sets document.title to "kit:ok", or paints the error on the stage and sets "kit:error <message>"
// (also for an error thrown before Kit.start, such as a reader that can't find its file).
const Kit = (() => {
  const DRAFT_DELAY_MS = 400, TOAST_MS = 1800;
  const params = new URLSearchParams(location.search);
  const shot = params.has("shot");
  let cfg, manifest, values, images = {}, state, variant, stateStart = 0, W = 1920, H = 1080;
  let approved = null, server = false, draftTimer, ids = 0, folds = {};
  const folder = location.pathname.replace(/[^/]*$/, "");

  const storeKey = () => `ui-preview:${location.pathname}:${variant}`;
  const pageKey = what => `ui-preview:${location.pathname}:${what}`; // "approved" (Save without serve.py), "folds"
  const remember = (what, data) => { try { localStorage.setItem(pageKey(what), JSON.stringify(data)); } catch { /* private window */ } };
  const recall = what => { try { return JSON.parse(localStorage.getItem(pageKey(what))); } catch { return null; } };
  const el = (tag, attrs = {}, ...children) => {
    const node = Object.assign(document.createElement(tag), attrs);
    node.append(...children);
    return node;
  };
  const isColour = spec => typeof spec.value === "string" && !spec.options;
  const hex8 = c => {
    let h = c.slice(1).toLowerCase();
    if (h.length <= 4) h = [...h].map(x => x + x).join("");
    return "#" + (h.length === 6 ? h + "ff" : h);
  };
  const fix = (spec, v) => (isColour(spec) && typeof v === "string" ? hex8(v) : v);
  const same = (spec, a, b) =>
    typeof a === "number" && typeof b === "number" && !spec.options ? Math.abs(a - b) < (spec.step || 0) / 2 + 1e-9 : a === b;

  function spec(value, unit) {
    if (typeof value === "boolean") return { value };
    if (typeof value === "string")
      return /^#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(value) ? { value: hex8(value) } : { value, options: [value] };
    const max = Math.max(4 * Math.abs(value), unit ? 16 : 1), int = Number.isInteger(value);
    return { value, min: value < 0 ? -max : 0, max: int ? Math.ceil(max) : max, step: int ? 1 : 0.01, unit };
  }

  function overlay(target, source) {
    for (const [group, g] of Object.entries(source || {}))
      for (const [name, value] of Object.entries(g || {}))
        if (target[group] && name in target[group]) target[group][name] = fix(cfg.groups[group].params[name], value);
  }

  function defaults(forVariant) {
    const out = {};
    for (const [group, g] of Object.entries(cfg.groups)) {
      out[group] = {};
      for (const [name, s] of Object.entries(g.params)) out[group][name] = fix(s, s.value);
    }
    const over = {};
    for (const [path, value] of Object.entries((cfg.variants || {})[forVariant] || {})) {
      const dot = path.lastIndexOf(".");
      (over[path.slice(0, dot)] ??= {})[path.slice(dot + 1)] = value;
    }
    overlay(out, over);
    return out;
  }

  /** What a value goes back to: the saved values.json for its variant, else the variant's defaults. */
  function baseline(forVariant) {
    const out = defaults(forVariant);
    if (approved?.variant === forVariant) overlay(out, approved.values);
    return out;
  }

  /** The baseline, plus this browser's tuning for each value whose baseline hasn't changed since it was tuned. */
  function load() {
    const base = baseline(variant);
    values = baseline(variant);
    if (shot) return;
    try {
      const stored = JSON.parse(localStorage.getItem(storeKey()));
      for (const [group, g] of Object.entries(stored.values))
        for (const [name, value] of Object.entries(g))
          if (base[group] && name in base[group] && stored.base[group]?.[name] === base[group][name]) overlay(values, { [group]: { [name]: value } });
    } catch { /* nothing stored, or an older format */ }
  }

  function save() {
    try { localStorage.setItem(storeKey(), JSON.stringify({ base: baseline(variant), values })); } catch { /* private window */ }
    status();
    if (!server) return;
    clearTimeout(draftTimer);
    draftTimer = setTimeout(() => write("values.draft.json", { ...exported(), draft: true }), DRAFT_DELAY_MS);
  }

  async function write(file, data) {
    try {
      const r = await fetch("/__save", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: folder + file, data }),
      });
      if (!r.ok) throw new Error((await r.json()).error);
      return true;
    } catch (e) {
      toast(`Couldn't save ${file}: ${e.message}`);
      return false;
    }
  }

  function changedCount() {
    const base = baseline(variant);
    let n = 0;
    for (const [group, g] of Object.entries(cfg.groups))
      if (!g.preview) for (const [name, s] of Object.entries(g.params)) if (!same(s, values[group][name], base[group][name])) n++;
    return n;
  }

  function status() {
    const box = document.getElementById("save-status");
    if (!box) return;
    const n = changedCount(), saved = server ? "values.json" : "your last Save";
    const spec = approved?.variant === variant
      ? `Defaults: ${saved}.${n ? ` ${n} changed from it.` : ""}`
      : (approved ? `${saved} holds variant ${approved.variant}.` : "Nothing saved yet.")
        + (n ? ` ${n} changed from variant ${variant}'s defaults.` : "");
    box.textContent = server
      ? `● Live: every change goes to values.draft.json. ${spec}`
      : `○ Not saving to disk (serve.py isn't running): Save copies the JSON and keeps it as this browser's defaults. ${spec}`;
    box.classList.toggle("live", server);
  }

  function toast(text) {
    const t = document.getElementById("toast");
    t.textContent = text;
    t.style.display = "block";
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => (t.style.display = "none"), TOAST_MS);
  }

  function setUrl() {
    const p = new URLSearchParams(location.search);
    p.set("s", state.id);
    p.set("v", variant);
    history.replaceState(null, "", "?" + p);
  }

  function press(selector, id) {
    document.querySelectorAll(selector).forEach(b => {
      b.classList.toggle("on", b.dataset.id === id);
      b.setAttribute("aria-pressed", b.dataset.id === id);
    });
  }

  function showState(id) {
    state = manifest.states.find(s => s.id === id) || manifest.states[0];
    stateStart = performance.now();
    document.querySelector("#bar .state").textContent = `${manifest.states.indexOf(state) + 1}/${manifest.states.length}  ${state.id}`;
    document.querySelector("#bar .caption").textContent = state.caption;
    press(".states button", state.id);
    if (!shot) setUrl();
  }

  function showVariant(id) {
    variant = manifest.variants[id] ? id : Object.keys(manifest.variants)[0];
    compare(false);
    load();
    buildControls();
    status();
    press(".variants button", variant);
    document.getElementById("variant-note").textContent = manifest.variants[variant]?.note || "";
    if (state && !shot) setUrl();
  }

  function hexParts(hex) {
    return { rgb: hex.slice(0, 7), alpha: parseInt(hex.slice(7, 9), 16) };
  }

  function control(group, name, spec, text) {
    const value = values[group][name];
    const def = baseline(variant)[group][name];
    const tracked = !cfg.groups[group].preview; // preview-only rows aren't the spec: never marked as changed
    const id = `kit-control-${++ids}`;
    const row = el("div", { className: "row" + (tracked && !same(spec, value, def) ? " changed" : "") });
    Object.assign(row.dataset, { group, key: name });
    const label = el("label", { textContent: text, htmlFor: id });
    label.title = spec.hint ? `${name}: ${spec.hint}` : name;
    const output = el("span", { className: "value" });
    const set = v => {
      values[group][name] = v;
      if (tracked) row.classList.toggle("changed", !same(spec, v, def));
      unlight();
      save();
      badges();
    };
    let input;
    if (spec.options) {
      input = el("select", { id });
      for (const o of spec.options) input.append(el("option", { value: o, textContent: o, selected: o === value }));
      input.onchange = () => set(typeof spec.value === "number" ? Number(input.value) : input.value);
      if (spec.unit) output.append(el("small", { textContent: spec.unit }));
    } else if (typeof spec.value === "boolean") {
      input = el("input", { type: "checkbox", id, checked: value });
      input.onchange = () => set(input.checked);
    } else if (isColour(spec)) {
      const { rgb, alpha } = hexParts(value);
      const picker = el("input", { type: "color", id, value: rgb, title: value });
      const a = el("input", { type: "range", min: 0, max: 255, step: 1, value: alpha, title: "opacity" });
      a.setAttribute("aria-label", `${name} opacity`);
      const show = () => (output.textContent = `${Math.round(Number(a.value) / 2.55)}%`);
      picker.oninput = a.oninput = () => {
        const v = picker.value + Number(a.value).toString(16).padStart(2, "0");
        picker.title = v;
        set(v);
        show();
      };
      show();
      input = el("div", { className: "colour" }, picker, a);
    } else {
      // A slider for the range, and a box to type an exact value (also outside the slider's range).
      input = el("input", { type: "range", id, min: spec.min, max: spec.max, step: spec.step, value });
      const box = el("input", { type: "number", className: "num", step: spec.step, value });
      box.setAttribute("aria-label", `${name}${spec.unit ? ` in ${spec.unit}` : ""}`);
      input.oninput = () => { box.value = input.value; set(Number(input.value)); };
      box.oninput = () => {
        if (box.value === "" || Number.isNaN(Number(box.value))) return;
        input.value = box.value;
        set(Number(box.value));
      };
      output.append(box, el("small", { textContent: spec.unit || "" }));
    }
    const revert = el("button", { className: "revert", textContent: "↺", title: `Back to ${def}` });
    revert.setAttribute("aria-label", `Revert ${name} to ${def}`);
    revert.onclick = () => { values[group][name] = def; save(); buildControls(); };
    row.append(label, input, output, revert);
    lightOn(row, [[group, name]]);
    row.addEventListener("pointerdown", unlight); // dragging: show the stage, not the highlight
    return row;
  }

  /** A collapsible group or section; its open state is remembered per page. */
  function fold(id, title, note, targets, className) {
    const summary = el("summary", {}, el("span", { className: "name", textContent: title }),
      el("small", { textContent: note }), el("span", { className: "badge" }));
    const box = el("details", { className, open: folds[id] ?? true }, summary);
    box.ontoggle = () => { if (folds[id] !== box.open) { folds[id] = box.open; remember("folds", folds); } };
    lightOn(summary, targets);
    return box;
  }

  function buildControls() {
    unlight();
    const box = document.getElementById("controls");
    box.replaceChildren();
    for (const [group, g] of Object.entries(cfg.groups)) {
      const rows = Object.entries(g.params).map(([name, s]) => {
        const slash = name.indexOf("/");
        const section = s.section ?? (slash > 0 ? name.slice(0, slash) : null);
        return { name, s, section, text: s.section == null && slash > 0 ? name.slice(slash + 1) : name };
      });
      const groupBox = fold(`g:${group}`, group, g.preview ? "preview only" : g.note || "",
        rows.map(r => [group, r.name]), "group" + (g.preview ? " preview" : ""));
      const sections = {};
      for (const r of rows) {
        let parent = groupBox;
        if (r.section) parent = sections[r.section] ??= groupBox.appendChild(fold(`s:${group}/${r.section}`, r.section, "",
          rows.filter(o => o.section === r.section).map(o => [group, o.name]), "section"));
        parent.append(control(group, r.name, r.s, r.text));
      }
      box.append(groupBox);
    }
    badges();
  }

  /** "n changed" on every group and section heading. */
  function badges() {
    for (const box of document.querySelectorAll("#controls details")) {
      const n = box.querySelectorAll(".row.changed").length;
      box.querySelector(":scope > summary .badge").textContent = n ? `${n} changed` : "";
    }
  }

  // Hover highlight. draw() is a pure function of the values and t, so drawing the frame again with the hovered values
  // pushed far off and comparing the two finds exactly what they change, on any page, without the page saying where.
  const CELL = 8; // compare in 8 px cells
  let lit = null, litTimer = 0, litDelay = 0, scratch = null, accent = null;

  function lightOn(node, targets) {
    node.addEventListener("pointerenter", () => light(targets));
    node.addEventListener("pointerleave", unlight);
    node.addEventListener("focusin", e => { if (e.target.matches(":focus-visible")) light(targets); });
    node.addEventListener("focusout", unlight);
  }

  function light(targets) {
    unlight();
    if (comparing) return;
    litDelay = setTimeout(() => { lit = targets; paintLight(); litTimer = setInterval(paintLight, 300); }, 120);
  }

  function unlight() {
    clearTimeout(litDelay);
    clearInterval(litTimer);
    lit = null;
    for (const id of ["highlight", "highlight-note"]) { const n = document.getElementById(id); if (n) n.hidden = true; }
  }

  /** A value far from v, so whatever it drives visibly moves or changes colour. */
  function poke(spec, v) {
    if (spec.options) return spec.options.length > 1 ? spec.options[(spec.options.indexOf(v) + 1) % spec.options.length] : v;
    if (typeof spec.value === "boolean") return !v;
    if (isColour(spec)) {
      const [r, g, b] = [1, 3, 5].map(i => parseInt(v.slice(i, i + 2), 16));
      return (r + b) / 2 > g ? "#00ff00ff" : "#ff00ffff";
    }
    const d = nudge(spec, v);
    return v + d <= spec.max ? v + d : v - d;
  }
  const nudge = (spec, v) => (spec.max - spec.min) / 4 || Math.abs(v) || 1;
  const now = () => (performance.now() - stateStart) / 1000;

  /** Draw a frame on scratch canvas i and read back its pixels (all of them, or the rect [x, y, w, h]). */
  function frameData(i, vals, t, rect = [0, 0, W, H]) {
    scratch ??= [0, 1].map(() => el("canvas", { width: W, height: H }).getContext("2d", { willReadFrequently: true }));
    const ctx = scratch[i];
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, W, H);
    cfg.draw(ctx, vals, { state: state.id, variant, t, images });
    return new Uint32Array(ctx.getImageData(...rect).data.buffer);
  }

  // Click the stage to find the values that change that spot: the reverse of the hover highlight. Each value is pushed
  // both ways (a size can grow away from the spot) and the pixels around the click are compared.
  function find(e) {
    const r = e.currentTarget.getBoundingClientRect(), k = W / r.width; // stage px per screen px
    const R = Math.max(2, Math.round(8 * k)), cx = Math.round((e.clientX - r.left) * k), cy = Math.round((e.clientY - r.top) * k);
    const x0 = Math.max(0, cx - R), y0 = Math.max(0, cy - R);
    const rect = [x0, y0, Math.min(W, cx + R) - x0, Math.min(H, cy + R) - y0];
    const t = now(), found = [];
    let base;
    try { base = frameData(0, values, t, rect); } catch { return; }
    for (const [group, g] of Object.entries(cfg.groups))
      for (const [name, spec] of Object.entries(g.params)) {
        const v = values[group][name];
        const tries = typeof spec.value === "number" && !spec.options ? [v + nudge(spec, v), v - nudge(spec, v)] : [poke(spec, v)];
        if (tries.some(p => {
          try {
            const px = frameData(1, { ...values, [group]: { ...values[group], [name]: p } }, t, rect);
            return px.some((c, i) => c !== base[i]);
          } catch { return false; }
        })) found.push([group, name]);
      }
    document.querySelectorAll("#controls .row.found").forEach(n => n.classList.remove("found"));
    const rows = found.map(([group, name]) =>
      document.querySelector(`#controls .row[data-group="${CSS.escape(group)}"][data-key="${CSS.escape(name)}"]`)).filter(Boolean);
    for (const row of rows) {
      row.classList.add("found");
      for (let d = row.closest("details"); d; d = d.parentElement.closest("details")) d.open = true;
    }
    rows[0]?.scrollIntoView({ block: "nearest" });
    toast(rows.length ? `${rows.length} value${rows.length > 1 ? "s" : ""} change${rows.length > 1 ? "" : "s"} this spot (marked in the panel).`
      : "No value changes this spot.");
  }

  // Hold Space or the Compare button: the stage shows the saved values (or the variant's defaults) instead of the tuning.
  let comparing = null;
  function compare(on) {
    if (on === !!comparing) return;
    unlight();
    comparing = on ? { ...values, ...Object.fromEntries(Object.entries(baseline(variant)).filter(([g]) => !cfg.groups[g].preview)) } : null;
    const saved = approved?.variant === variant ? (server ? "the saved values.json" : "your last Save") : `variant ${variant}'s defaults`;
    const note = document.getElementById("compare-note");
    note.textContent = `Showing ${saved}${changedCount() ? "" : " (nothing changed from them)"}. Let go to see your tuning.`;
    note.hidden = !on;
    document.getElementById("compare").classList.toggle("on", on);
  }

  function paintLight() {
    if (!lit) return;
    accent ??= getComputedStyle(document.body).getPropertyValue("--accent").trim() || "#5eaeff";
    const poked = structuredClone(values);
    for (const [g, n] of lit) poked[g][n] = poke(cfg.groups[g].params[n], values[g][n]);
    const t = now();
    let a, b;
    try { a = frameData(0, values, t); b = frameData(1, poked, t); } catch { return unlight(); }
    const gw = Math.ceil(W / CELL), gh = Math.ceil(H / CELL), hit = new Uint8Array(gw * gh);
    let any = false;
    for (let y = 0; y < H; y++) {
      const row = y * W, cells = ((y / CELL) | 0) * gw;
      for (let x = 0; x < W; x++) if (a[row + x] !== b[row + x]) { hit[cells + ((x / CELL) | 0)] = 1; any = true; }
    }
    const mask = document.getElementById("highlight");
    mask.hidden = !any;
    document.getElementById("highlight-note").hidden = any;
    if (!any) return;
    // One box per area that changed: cells closer than GAP cells join the same area, and boxes that overlap or line up
    // within REACH merge. Darken the rest and outline each box.
    const GAP = 4, PAD = 6, REACH = Math.max(W, H) / 3;
    const seen = new Uint8Array(gw * gh);
    let boxes = [];
    for (let start = 0; start < gw * gh; start++) {
      if (!hit[start] || seen[start]) continue;
      const box = [gw, gh, 0, 0], todo = [start];
      seen[start] = 1;
      while (todo.length) {
        const i = todo.pop(), x = i % gw, y = (i / gw) | 0;
        box[0] = Math.min(box[0], x); box[1] = Math.min(box[1], y); box[2] = Math.max(box[2], x + 1); box[3] = Math.max(box[3], y + 1);
        for (let yy = Math.max(0, y - GAP); yy <= Math.min(gh - 1, y + GAP); yy++)
          for (let xx = Math.max(0, x - GAP); xx <= Math.min(gw - 1, x + GAP); xx++) {
            const j = yy * gw + xx;
            if (hit[j] && !seen[j]) { seen[j] = 1; todo.push(j); }
          }
      }
      boxes.push(box.map(c => c * CELL));
    }
    boxes = boxes.map(([x0, y0, x1, y1]) => [Math.max(0, x0 - PAD), Math.max(0, y0 - PAD), Math.min(W, x1 + PAD), Math.min(H, y1 + PAD)]);
    for (let merged = true; merged;) {
      merged = false;
      for (let i = 0; i < boxes.length && !merged; i++) for (let j = i + 1; j < boxes.length && !merged; j++) {
        const a = boxes[i], b = boxes[j];
        const gapX = Math.max(b[0] - a[2], a[0] - b[2]), gapY = Math.max(b[1] - a[3], a[1] - b[3]);
        // Overlapping, or side by side on one row or column (a panel's four corners when its radius changes).
        if ((gapX <= 0 && gapY <= 0) || (gapY <= 0 && gapX < REACH) || (gapX <= 0 && gapY < REACH)) {
          boxes[i] = [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])];
          boxes.splice(j, 1);
          merged = true;
        }
      }
    }
    if (mask.width !== W) { mask.width = W; mask.height = H; }
    const ctx = mask.getContext("2d"), px = W / (mask.getBoundingClientRect().width || W); // stage px per screen px
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "rgba(0, 0, 0, 0.6)";
    ctx.fillRect(0, 0, W, H);
    ctx.globalCompositeOperation = "destination-out";
    for (const [x0, y0, x1, y1] of boxes) { ctx.beginPath(); ctx.roundRect(x0, y0, x1 - x0, y1 - y0, 6 * px); ctx.fill(); }
    ctx.globalCompositeOperation = "source-over";
    ctx.strokeStyle = accent;
    ctx.lineWidth = 2 * px;
    for (const [x0, y0, x1, y1] of boxes) { ctx.beginPath(); ctx.roundRect(x0, y0, x1 - x0, y1 - y0, 6 * px); ctx.stroke(); }
  }

  function exported() {
    const out = {};
    for (const [group, g] of Object.entries(cfg.groups)) if (!g.preview) out[group] = { ...values[group] };
    return { feature: cfg.feature, variant, values: out };
  }

  async function copyJson() {
    const text = JSON.stringify(exported(), null, 2);
    try {
      await navigator.clipboard.writeText(text);
      toast("Copied. Paste it in the chat.");
    } catch {
      window.prompt("Copy this JSON:", text);
    }
  }

  function pasteJson() {
    const text = window.prompt("Paste JSON from Copy JSON (or a values.json):");
    if (!text) return;
    try {
      const data = JSON.parse(text);
      if (data.variant && manifest.variants[data.variant]) showVariant(data.variant);
      overlay(values, data.values || data);
      save();
      buildControls();
      toast("Loaded.");
    } catch (e) {
      toast("That isn't valid JSON: " + e.message);
    }
  }

  function reset() {
    try { localStorage.removeItem(storeKey()); } catch { /* nothing saved */ }
    load();
    save();
    buildControls();
    toast(approved?.variant === variant ? "Back to the saved values." : `Variant ${variant} back to its defaults.`);
  }

  async function saveDefault() {
    const data = exported();
    if (server) {
      if (!(await write("values.json", data))) return;
    } else {
      await copyJson();
      remember("approved", data);
    }
    approved = data;
    buildControls();
    status();
    toast(server ? "Saved values.json: these are the defaults now."
      : "Copied the JSON, and kept these as the defaults in this browser.");
  }

  function buildPage() {
    document.title = manifest.title;
    const canvas = el("canvas", { id: "stage", width: W, height: H });
    canvas.style.width = W + "px"; canvas.style.height = H + "px";
    const compareButton = el("button", { id: "compare", textContent: "Compare", title: "Hold to see the saved values instead of your tuning (or hold Space)" });
    compareButton.onpointerdown = () => compare(true);
    compareButton.onpointerup = compareButton.onpointerleave = compareButton.onpointercancel = () => compare(false);
    const zoomButton = el("button", { id: "zoom", textContent: "Fit", title: "Zoom: fit the window, real size, double (Z, toward the pointer)" });
    zoomButton.onclick = () => setZoom();
    const bar = el("div", { id: "bar" }, el("h1", { textContent: manifest.title }),
      el("span", { className: "state" }), el("span", { className: "caption" }), el("span", { className: "tools" }, compareButton, zoomButton));
    const mask = el("canvas", { id: "highlight", hidden: true });
    mask.style.width = W + "px"; mask.style.height = H + "px";
    canvas.title = "Click to find the values that change this spot";
    canvas.onclick = find;
    const note = el("div", { id: "highlight-note", className: "stage-note", hidden: true, textContent: "No visible change in this state: try another state." });
    const compareNote = el("div", { id: "compare-note", className: "stage-note", hidden: true });
    const area = el("div", { id: "stage-area" }, bar,
      el("div", { id: "stage-wrap" }, el("div", { id: "stage-scroll" }, canvas, mask), note, compareNote));

    const variants = el("div", { className: "variants" });
    for (const [id, v] of Object.entries(manifest.variants)) {
      const b = el("button", { textContent: `${id}  ${v.name}` });
      b.dataset.id = id;
      b.onclick = () => showVariant(id);
      variants.append(b);
    }
    const states = el("div", { className: "states" });
    for (const s of manifest.states) {
      const b = el("button", { textContent: s.id, title: s.caption });
      b.dataset.id = s.id;
      b.onclick = () => showState(s.id);
      states.append(b);
    }
    const rec = manifest.recommend;
    const actions = el("div", { className: "actions" },
      el("button", { className: "primary", textContent: "Save", title: "Make these the approved values and the page's defaults (Ctrl/Cmd+S)", onclick: saveDefault }),
      el("button", { textContent: "Copy JSON", title: "Copy the values as JSON", onclick: copyJson }),
      el("button", { textContent: "Paste JSON", title: "Load values from a pasted JSON", onclick: pasteJson }),
      el("button", { textContent: "Reset", title: "Every value back to the defaults", onclick: reset }));
    const collapse = el("button", { id: "collapse", textContent: "⇥", title: "Hide or show the panel" });
    collapse.setAttribute("aria-label", "Hide or show the panel");
    // The panel scrolls; Save and the save status stay pinned at its foot.
    const panel = el("div", { id: "panel" }, collapse,
      el("div", { id: "panel-body" },
        el("h2", { textContent: "Variants" }), variants, el("p", { className: "note", id: "variant-note" }),
        rec ? el("div", { className: "recommend" }, el("b", { textContent: `Recommended: ${rec.variant}.` }), ` ${rec.why}`) : "",
        el("h2", { textContent: "States" }, el("small", { textContent: "← → to step" })), states,
        el("h2", { textContent: "Values" }, el("small", { textContent: "hover to see, click the stage to find" })),
        el("div", { id: "controls" })),
      el("div", { id: "panel-foot" }, actions, el("p", { id: "save-status", className: "note" })));
    collapse.onclick = () => { panel.classList.toggle("collapsed"); fit(); };
    document.body.append(area, panel, el("div", { id: "toast", role: "status" }));
    if (shot) document.body.classList.add("shot");
    return canvas;
  }

  // Zoom: 0 fits the stage to the window; 1 and 2 are real and double size, scrolled around the stage.
  const ZOOMS = [0, 1, 2];
  let zoom = 0, pointer = null;

  /** Next zoom level, keeping the stage point under `at` (client x, y; default the view's centre) where it is. */
  function setZoom(at) {
    const view = document.getElementById("stage-scroll"), v = view.getBoundingClientRect();
    at ??= [v.left + v.width / 2, v.top + v.height / 2];
    const s = document.getElementById("stage").getBoundingClientRect();
    const sx = Math.min(W, Math.max(0, (at[0] - s.left) * W / s.width)), sy = Math.min(H, Math.max(0, (at[1] - s.top) * H / s.height));
    zoom = ZOOMS[(ZOOMS.indexOf(zoom) + 1) % ZOOMS.length];
    const button = document.getElementById("zoom");
    button.textContent = zoom ? `${zoom === 1 ? "1:1" : zoom + "×"}` : "Fit";
    button.classList.toggle("on", zoom > 0);
    const [x, y, scale] = fit();
    view.scrollLeft = x + sx * scale - (at[0] - v.left);
    view.scrollTop = y + sy * scale - (at[1] - v.top);
  }

  function fit() {
    if (shot) return;
    const view = document.getElementById("stage-scroll");
    view.classList.toggle("zoomed", zoom > 0);
    const scale = zoom || Math.min(view.clientWidth / W, view.clientHeight / H);
    const x = Math.max(0, (view.clientWidth - W * scale) / 2), y = Math.max(0, (view.clientHeight - H * scale) / 2);
    for (const id of ["stage", "highlight"]) document.getElementById(id).style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
    return [x, y, scale];
  }

  function checkVariants() {
    const declared = Object.keys(manifest.variants), given = Object.keys(cfg.variants || {});
    for (const v of declared) if (!given.includes(v)) console.warn(`Kit: manifest variant "${v}" has no entry in Kit.start's variants.`);
    for (const v of given) if (!declared.includes(v)) console.warn(`Kit: variant "${v}" in Kit.start isn't in manifest.json, so it can't be picked.`);
  }

  function fail(error) {
    console.error(error);
    if (shot) document.title = `kit:error ${error.message}`;
    const box = el("pre", { id: "kit-error", textContent: `Preview failed:\n${error.stack || error}` });
    box.style.width = W + "px"; box.style.height = H + "px";
    document.body.className = shot ? "shot" : "";
    document.body.replaceChildren(box);
  }

  async function boot(config) {
    cfg = config;
    manifest = await (await fetch("manifest.json", { cache: "no-store" })).json();
    [W, H] = manifest.stage || [1920, 1080];
    checkVariants();
    await Promise.all([...(cfg.fonts || []).map(f => document.fonts.load(f)), ...[...document.fonts].map(f => f.load().catch(() => {}))]);
    if (!params.has("defaults"))
      approved = await fetch("values.json", { cache: "no-store" }).then(r => (r.ok ? r.json() : null)).catch(() => null);
    if (!shot) server = await fetch("/__preview", { cache: "no-store" }).then(r => r.ok).catch(() => false);
    if (!shot && !server && !approved && !params.has("defaults")) approved = recall("approved"); // Save without serve.py
    folds = recall("folds") || {};
    await Promise.all(Object.entries(cfg.images || {}).map(([key, src]) => new Promise((ok, no) => {
      const img = new Image();
      img.onload = () => ok((images[key] = img));
      img.onerror = () => no(new Error("missing image " + src));
      img.src = src;
    })));

    const canvas = buildPage();
    const ctx = canvas.getContext("2d");
    showVariant(params.get("v") || approved?.variant);
    showState(params.get("s"));
    const paint = t => {
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.imageSmoothingEnabled = false;
      ctx.clearRect(0, 0, W, H);
      cfg.draw(ctx, comparing ?? values, { state: state.id, variant, t, images });
    };
    // Headless Chrome dumps the page before any animation frame runs: draw the shot synchronously.
    if (shot) return paint(Number(params.get("t") ?? state.shotTime ?? 0));

    fit();
    addEventListener("resize", () => fit());
    const view = document.getElementById("stage-scroll");
    view.addEventListener("pointermove", e => (pointer = [e.clientX, e.clientY]));
    view.addEventListener("pointerleave", () => (pointer = null));
    const typing = "textarea, select, [contenteditable], input:not([type=range], [type=checkbox], [type=color], [type=button])";
    addEventListener("keydown", e => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        if (e.target.matches("textarea, [contenteditable], input:not([type=range], [type=checkbox], [type=color], [type=number])")) return;
        e.preventDefault();
        return saveDefault();
      }
      if (e.key === " " && !e.target.matches(typing)) {
        e.preventDefault();
        if (!e.target.matches("input[type=range]")) e.target.blur?.(); // or Space would also press the focused button
        return e.repeat || compare(true);
      }
      if (e.key === "Escape") document.querySelectorAll("#controls .row.found").forEach(n => n.classList.remove("found"));
      if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key.toLowerCase() === "z") setZoom(pointer ?? undefined);
      const i = manifest.states.indexOf(state);
      if (e.key === "ArrowRight") showState(manifest.states[(i + 1) % manifest.states.length].id);
      if (e.key === "ArrowLeft") showState(manifest.states[(i - 1 + manifest.states.length) % manifest.states.length].id);
    });
    addEventListener("keyup", e => { if (e.key === " ") compare(false); });
    addEventListener("blur", () => compare(false));
    // A draw() that throws for some slider value must not end the loop: the slider has to stay movable to undo it.
    const frame = now => {
      requestAnimationFrame(frame);
      try {
        paint((now - stateStart) / 1000);
      } catch (e) {
        if (e.message !== frame.error) console.error(e);
        frame.error = e.message;
        toast(`draw() failed: ${e.message}`);
      }
    };
    requestAnimationFrame(frame);
  }

  // A page that fails before it reaches Kit.start (a reader that can't find the project's files) would otherwise stay
  // blank, and its shot would never finish: show that error the same way.
  let started = false;
  const early = e => {
    if (started) return;
    const x = e.reason ?? e.error ?? e.message;
    fail(x instanceof Error ? x : new Error(String(x)));
  };
  addEventListener("error", early);
  addEventListener("unhandledrejection", early);

  async function start(config) {
    started = true;
    try {
      await boot(config);
      if (shot) document.title = "kit:ok";
    } catch (e) {
      fail(e);
    }
  }

  return { start, spec };
})();
