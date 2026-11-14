// Optional helpers for Unreal projects, loaded after kit.js (they use Kit.spec). A .uasset is binary, so the reader
// takes a DataTable exported from the editor (right-click the asset > Export as JSON or CSV), kept anywhere under the
// project:
//   JSON: [ { "Name": "Default", "PanelColor": { "R": 0.05, "G": 0.05, "B": 0.05, "A": 0.9 }, "CornerRadius": 8 } ]
//   CSV:  ---,PanelColor,CornerRadius
//         Default,"(R=0.050000,G=0.050000,B=0.050000,A=0.900000)",8.000000
//
//   UnrealTheme.configure({ root: "../../../" });   // from <mockups>/<feature>/ to the project root (the default)
//   UnrealTheme.loadTable("Content/UI/DT_HudStyle.json")
//     .then(() => Kit.start({ groups: { ...mine, ...UnrealTheme.groups() }, draw(ctx, v, s) { UnrealTheme.use(v); ... } }))
//
// API: configure({ root }), loadTable(path), groups(), use(values), get(row, field).
//   get(row, field) returns the tuned value: row is the row name ("Default"), or "<file stem>/<RowName>" when two
//   loaded tables share row names; field is the flattened field name ("CornerRadius", "Padding/Left").
//   (UnityTheme's get takes (name, group?) instead: Unity names are unique per file, Unreal ones repeat per row.)
//
// Groups are "table: <file stem>/<RowName>", keys the row's field names; nested structs are flattened as "Parent/Child"
// (an FSlateColor shows as "Tint/SpecifiedColor"), arrays are skipped. Numbers are sliders, strings and enums a
// one-option dropdown (shown, not tunable), bools a checkbox. Colours become "#rrggbbaa" sRGB. A struct with R, G, B is
// read as an FColor (sRGB bytes, taken as is) only when every channel, A included, is a whole number and at least one is
// above 1; anything else is an FLinearColor (linear light, given the sRGB curve). So an FColor whose channels are all 0
// or 1 reads as linear, and an HDR FLinearColor written with whole numbers (R=4,G=0,B=0) reads as an FColor. An HDR
// FLinearColor (a channel above 1) is clamped to 1 for the panel, with a console note: tuning it saves the clamped value.
// A malformed struct (an unclosed quote or bracket) fails the load with the file, row and field named.
//
// There is no apply script for Unreal: write the tuned values into the exported JSON (FLinearColor back through the
// inverse sRGB curve) and re-import it over the DataTable (Reimport, or the editor's Import from JSON).
const UnrealTheme = (() => {
  let ROOT = "../../../";
  const tables = []; // { group, row, note, fields: { name: value } }, in load order
  let tuned = {};

  const srgb = c => (c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055);
  const hex2 = x => Math.round(Math.min(1, Math.max(0, x)) * 255).toString(16).padStart(2, "0");

  function colour(o, where) {
    const c = ["R", "G", "B", "A"].map(k => Number(o[k] ?? NaN));
    const rgb = c.slice(0, 3), a = Number.isNaN(c[3]) ? null : c[3];
    const all = a === null ? rgb : c;
    if (all.every(Number.isInteger) && all.some(x => x > 1)) return "#" + [...rgb, a ?? 255].map(x => hex2(x / 255)).join("");
    if (all.some(x => x > 1)) console.info(`UnrealTheme: ${where} is HDR (${all.join(", ")}); the panel shows it clamped to 0–1.`);
    return "#" + [...rgb.map(srgb), a ?? 1].map(hex2).join("");
  }

  function scalar(s) {
    s = s.trim();
    if (/^-?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(s)) return Number(s);
    if (/^(true|false)$/i.test(s)) return s.toLowerCase() === "true";
    return s;
  }

  // Unreal's export text: (R=1.000000,G=0.5,...), nested (SpecifiedColor=(R=...),ColorUseRule=UseColor_Specified),
  // quoted strings with \" escapes, and arrays (1,2,3), which come back as JS arrays. Every step moves forward and an
  // unclosed quote or bracket throws, so bad input can't loop.
  function parseStruct(s) {
    let i = 0;
    const value = depth => {
      if (depth > 64) throw new Error("structs nested too deep");
      if (s[i] === "(") {
        const open = i++;
        const o = {}, list = [];
        while (s[i] !== ")") {
          if (i >= s.length) throw new Error(`unclosed "(" at ${open}`);
          const m = /^(\w+)=/.exec(s.slice(i));
          if (m) { i += m[0].length; o[m[1]] = value(depth + 1); } else list.push(value(depth + 1));
          if (s[i] === ",") i++;
          else if (s[i] !== ")" && i < s.length) throw new Error(`unexpected "${s[i]}" at ${i}`);
        }
        i++;
        return list.length ? list : o;
      }
      if (s[i] === '"') {
        let j = i + 1;
        while (j < s.length && s[j] !== '"') j += s[j] === "\\" ? 2 : 1;
        if (j >= s.length) throw new Error(`unclosed quote at ${i}`);
        const v = s.slice(i + 1, j).replace(/\\(.)/g, "$1");
        i = j + 1;
        return v;
      }
      const start = i;
      while (i < s.length && !",)".includes(s[i])) i++;
      return scalar(s.slice(start, i));
    };
    const v = value(0);
    if (i < s.length) throw new Error(`unexpected "${s[i]}" at ${i}`);
    return v;
  }

  function flatten(v, name, out, where) {
    if (v === null || Array.isArray(v)) return;
    if (typeof v === "object") {
      if ("R" in v && "G" in v && "B" in v) out[name] = colour(v, `${where}.${name}`);
      else for (const [k, x] of Object.entries(v)) flatten(x, name ? `${name}/${k}` : k, out, where);
    } else if (typeof v === "string" && /^\(.*\)$/s.test(v)) {
      let parsed;
      try { parsed = parseStruct(v); } catch (e) { throw new Error(`UnrealTheme: ${where}.${name}: ${e.message} in ${v}`); }
      flatten(parsed, name, out, where);
    } else out[name] = v;
  }

  function csv(text) {
    const rows = [];
    let row = [], cell = "", quoted = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (quoted) {
        if (c !== '"') cell += c;
        else if (text[i + 1] === '"') { cell += '"'; i++; } else quoted = false;
      } else if (c === '"') quoted = true;
      else if (c === ",") { row.push(cell); cell = ""; }
      else if (c === "\n") { row.push(cell); rows.push(row); row = []; cell = ""; }
      else if (c !== "\r") cell += c;
    }
    if (cell || row.length) { row.push(cell); rows.push(row); }
    return rows.filter(r => r.some(Boolean));
  }

  async function loadTable(path) {
    const r = await fetch(ROOT + path, { cache: "no-store" });
    if (!r.ok) throw new Error("missing " + path);
    const text = await r.text();
    let rows;
    if (/\.csv$/i.test(path)) {
      const [head, ...body] = csv(text);
      rows = body.map(cells => Object.fromEntries(cells.map((c, j) => [j === 0 ? "Name" : head[j], j === 0 ? c : scalar(c)])));
    } else rows = JSON.parse(text);
    const stem = path.split("/").pop().replace(/\.[^.]+$/, "");
    for (const { Name, ...fields } of rows) {
      const out = {};
      flatten(fields, "", out, `${path} row ${Name}`);
      tables.push({ group: `table: ${stem}/${Name}`, row: String(Name), note: path, fields: out });
    }
  }

  function groups() {
    const out = {};
    for (const t of tables)
      out[t.group] = { note: t.note, params: Object.fromEntries(Object.entries(t.fields).map(([k, v]) => [k, Kit.spec(v)])) };
    return out;
  }

  function get(row, field) {
    const t = tables.find(t => t.group === `table: ${row}`) || tables.find(t => t.row === row);
    if (!t) return undefined;
    return tuned[t.group]?.[field] ?? t.fields[field];
  }

  function configure(o) { if (o.root) ROOT = o.root; }

  /** Call at the top of draw() so get() sees the tuning panel's values. */
  function use(values) { tuned = values; }

  return { configure, loadTable, groups, get, use, tables };
})();
