// Optional helpers for Unity projects, loaded after kit.js (they use Kit.spec): the tuning panel starts from the
// values the game ships, read from two kinds of project file:
//   - UI Toolkit .uss: custom properties (--name: value;) declared in any rule, usually :root. Keys keep the leading
//     "--" so the JSON round-trips; apply_uss.py writes a tuned values.json back into the .uss.
//   - a ScriptableObject .asset (or the MonoBehaviour sections of a .prefab), Unity's YAML: its serialized fields.
//
//   UnityTheme.configure({ root: "../../../" });   // from <mockups>/<feature>/ to the project root (the default)
//   Promise.all([UnityTheme.loadUss("Assets/UI/Theme.uss"), UnityTheme.loadAsset("Assets/UI/HudStyle.asset")])
//     .then(() => Kit.start({ groups: { ...mine, ...UnityTheme.groups() }, draw(ctx, v, s) { UnityTheme.use(v); ... } }))
//
// API: configure({ root }), loadUss(path), loadAsset(path, { guid? }), groups(), use(values), get(name, group?).
//   get(name) returns the tuned value of the first loaded source that has that name ("--accent" from a .uss,
//   "cornerRadius" from an asset); pass the group ("uss: Theme", "asset: HudStyle") when two sources share a name.
//   (UnrealTheme's get takes (row, field) instead: a DataTable row is always needed there.)
//
// Groups are "uss: <file stem>" and "asset: <m_Name or file stem>". Colours become "#rrggbbaa" (Unity stores Color
// fields as the gamma values the inspector shows, so no conversion). Numbers are sliders; a .uss length keeps its unit
// (px, %, s, ms, deg) on the slider and in a range that suits it. Strings are a one-option dropdown (shown, not
// tunable). A .uss variable that is only var(--other) is left out of the panel and follows its target. Nested
// serialized fields are flattened as "parent/child"; lists and object references are skipped.
// Unity's own header fields (m_Script, m_Enabled, ...) are skipped; m_Name names the group; your own m_-prefixed fields
// are kept. Unity saves a bool as 0/1, which reads as a number, except that a 0/1 field whose name (after any m_ or _)
// starts with is/has/use/show/enable followed by a capital, digit or _ (isOpen, m_ShowIcons, enableGlow) becomes a
// checkbox, so it comes out of the JSON as true/false: write it back as 1/0.
const UnityTheme = (() => {
  let ROOT = "../../../";
  const sources = []; // { group, note, fields: { name: { value, unit?, alias? } } }, in load order
  let tuned = {};

  const HEADER = new Set(["m_ObjectHideFlags", "m_CorrespondingSourceObject", "m_PrefabInstance", "m_PrefabAsset",
    "m_GameObject", "m_Enabled", "m_EditorHideFlags", "m_Script", "m_Name", "m_EditorClassIdentifier"]);
  const BOOLISH = /^(?:m_|_)?(?:[iI]s|[hH]as|[uU]se|[sS]how|[eE]nabled?)(?:[A-Z0-9_]|$)/;
  const UNIT_MAX = { "%": 100, deg: 360, s: 2, ms: 1000 }; // the least a slider spans, per unit

  const hex2 = x => Math.round(Math.min(1, Math.max(0, x)) * 255).toString(16).padStart(2, "0");
  const toHex = (r, g, b, a = 1) => "#" + [r, g, b, a].map(hex2).join("");
  const channel = (x, scale) => (x.endsWith("%") ? Number(x.slice(0, -1)) / 100 : Number(x) / scale);

  function cssColor(s) {
    let m;
    if ((m = s.match(/^#([0-9a-f]{3,8})$/i))) {
      let h = m[1];
      if (h.length <= 4) h = [...h].map(c => c + c).join("");
      if (h.length === 6) h += "ff";
      if (h.length === 8) return "#" + h.toLowerCase();
    }
    if ((m = s.match(/^rgba?\(([^)]*)\)$/i))) {
      const parts = m[1].split(/[\s,/]+/).filter(Boolean);
      if (parts.length < 3 || parts.length > 4) return null;
      const c = [...parts.slice(0, 3).map(x => channel(x, 255)), parts[3] ? channel(parts[3], 1) : 1];
      return c.every(Number.isFinite) ? toHex(...c) : null;
    }
    return null;
  }

  async function fetchText(path) {
    const r = await fetch(ROOT + path, { cache: "no-store" });
    if (!r.ok) throw new Error("missing " + path);
    return (await r.text()).replace(/\r\n?/g, "\n");
  }

  const stem = path => path.split("/").pop().replace(/\.[^.]+$/, "");

  function ussValue(raw) {
    const s = raw.trim();
    let m;
    const c = cssColor(s);
    if (c) return { value: c };
    if ((m = s.match(/^(-?\d*\.?\d+)(px|%|ms|s|deg)?$/))) return { value: Number(m[1]), unit: m[2] };
    if ((m = s.match(/^var\(\s*(--[\w-]+)\s*\)$/))) return { value: s, alias: m[1] };
    if ((m = s.match(/^"(.*)"$|^'(.*)'$/))) return { value: m[1] ?? m[2] };
    return { value: s };
  }

  async function loadUss(path) {
    const text = (await fetchText(path)).replace(/\/\*[\s\S]*?\*\//g, "");
    const fields = {};
    // Only after { or ; so BEM selectors like .button--primary:hover aren't read as declarations.
    for (const m of text.matchAll(/[{;]\s*(--[\w-]+)\s*:\s*([^;}]+)/g))
      if (!(m[1] in fields)) fields[m[1]] = ussValue(m[2]);
    sources.push({ group: `uss: ${stem(path)}`, note: path, fields });
  }

  function yamlValue(s) {
    s = s.trim();
    let m;
    if ((m = s.match(/^\{(.*)\}$/))) {
      const o = {};
      for (const part of m[1].split(",")) {
        const [k, v] = part.split(":").map(x => x.trim());
        o[k] = Number(v);
      }
      return o;
    }
    if (/^-?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(s)) return Number(s);
    if (s === "true" || s === "false") return s === "true";
    if ((m = s.match(/^"(.*)"$/))) { try { return JSON.parse(s); } catch { return m[1]; } }
    if ((m = s.match(/^'(.*)'$/))) return m[1].replace(/''/g, "'");
    return s;
  }

  function addField(fields, name, v) {
    if (typeof v !== "object") fields[name] = { value: (v === 0 || v === 1) && BOOLISH.test(name.split("/").pop()) ? v === 1 : v };
    else if ("r" in v && "g" in v && "b" in v) fields[name] = { value: toHex(v.r, v.g, v.b, v.a ?? 1) };
    else if (!("fileID" in v)) for (const [k, x] of Object.entries(v)) fields[`${name}/${k}`] = { value: x }; // Vector2, Rect...
  }

  // One MonoBehaviour document: "  key: value" fields, nested mappings flattened, lists and object references skipped.
  function parseMonoBehaviour(body) {
    const fields = {};
    let name = "", stack = [], listIndent = -1;
    for (const line of body.split("\n").slice(1)) {
      const indent = line.match(/^ */)[0].length;
      if (/^ *- /.test(line)) { listIndent = indent; continue; }
      if (listIndent >= 0 && indent > listIndent) continue;
      listIndent = -1;
      const m = line.match(/^ *([^\s:#][^:]*):(?: (.*))?$/);
      if (!m) continue;
      while (stack.length && stack[stack.length - 1].indent >= indent) stack.pop();
      const key = m[1], raw = (m[2] ?? "").trim();
      if (stack.length === 0 && key === "m_Name") name = raw;
      if (!raw) { stack.push({ indent, key }); continue; }
      if (HEADER.has(stack.length ? stack[0].key : key) || raw.startsWith("[")) continue;
      addField(fields, [...stack.map(s => s.key), key].join("/"), yamlValue(raw));
    }
    return { name, fields };
  }

  /** opts.guid: only the MonoBehaviour whose m_Script has this guid (from the script's .cs.meta), for prefabs. */
  async function loadAsset(path, opts = {}) {
    const docs = (await fetchText(path)).split(/^--- !u!(\d+) &-?\d+.*$/m);
    for (let i = 1; i < docs.length; i += 2) {
      if (docs[i] !== "114") continue;
      const body = docs[i + 1].replace(/^\n/, "");
      if (opts.guid && !body.includes(`guid: ${opts.guid}`)) continue;
      const { name, fields } = parseMonoBehaviour(body);
      let group = `asset: ${name || stem(path)}`;
      while (sources.some(s => s.group === group)) group += "'";
      sources.push({ group, note: path, fields });
    }
  }

  function find(name, group) {
    return sources.find(s => (!group || s.group === group) && name in s.fields);
  }
  const aliasTarget = (s, f) => f.alias && (find(f.alias, s.group) || find(f.alias));

  // Kit.spec sizes every unit's slider like px; seconds, degrees and percentages get a range of their own.
  function spec({ value: v, unit }) {
    if (typeof v !== "number" || !(unit in UNIT_MAX)) return Kit.spec(v, unit);
    const max = Math.max(4 * Math.abs(v), UNIT_MAX[unit]), int = Number.isInteger(v);
    return { value: v, min: v < 0 ? -max : 0, max: int ? Math.ceil(max) : max, step: int ? 1 : 0.01, unit };
  }

  function groups() {
    const out = {};
    for (const s of sources) {
      const params = {};
      for (const [name, f] of Object.entries(s.fields))
        if (!aliasTarget(s, f)) params[name] = spec(f);
      out[s.group] = { note: s.note, params };
    }
    return out;
  }

  function get(name, group) {
    const s = find(name, group);
    if (!s) return undefined;
    const f = s.fields[name];
    const target = aliasTarget(s, f);
    if (target) return get(f.alias, target.group);
    return tuned[s.group]?.[name] ?? f.value;
  }

  function configure(o) { if (o.root) ROOT = o.root; }

  /** Call at the top of draw() so get() sees the tuning panel's values. */
  function use(values) { tuned = values; }

  return { configure, loadUss, loadAsset, groups, get, use, sources };
})();
