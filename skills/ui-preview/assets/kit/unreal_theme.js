// Optional helpers for Unreal projects, loaded after kit.js (they use Kit.spec). Two sources:
//
// 1. C++ class defaults (UDeveloperSettings and other UCLASSes): loadClass reads the header, and for a Config class the
//    overrides in Config/Default<Config>.ini. apply_unreal.py writes the approved values back (ini or header).
//   UnrealTheme.loadClass("Source/MyGame/UI/HudSettings.h", { categories: ["Panel"] })
//     .then(() => Kit.start({ groups: { ...UnrealTheme.groups() }, draw(ctx, v, s) { UnrealTheme.use(v);
//        const w = UnrealTheme.get("HudSettings", "PanelWidth"), x = UnrealTheme.get("HudSettings", "Offset/X"); ... } }))
//   One group per class, named without its U / A / F prefix; keys are the UPROPERTY names (struct members "Prop/X"),
//   each in a section named after its Category, its comment as the hint, ClampMin / ClampMax / UIMin / UIMax as the
//   slider's range. Read: float, double, intN / uintN, bool, enums declared in the same header (a dropdown),
//   FLinearColor (linear, shown through the sRGB curve), FColor (sRGB bytes), FVector2D / FVector / FIntPoint / FMargin,
//   from literal defaults (`= 4.f`, `{1.f, 2.f}`, `FLinearColor(FColor(0xFF, 0xC3, 0x0F))`, `FColor::White`, none = 0).
//   Anything else is left out with a console note. A value the class doesn't have yet goes in the same group (add its
//   spec to groups()[Class].params): apply_unreal.py lists it with a declaration to paste.
//
// 2. A DataTable: a .uasset is binary, so the reader takes a DataTable exported from the editor (right-click the
// asset > Export as JSON or CSV), kept anywhere under the project:
//   JSON: [ { "Name": "Default", "PanelColor": { "R": 0.05, "G": 0.05, "B": 0.05, "A": 0.9 }, "CornerRadius": 8 } ]
//   CSV:  ---,PanelColor,CornerRadius
//         Default,"(R=0.050000,G=0.050000,B=0.050000,A=0.900000)",8.000000
//
//   UnrealTheme.configure({ root: "../../../" });   // from <mockups>/<feature>/ to the project root (the default)
//   UnrealTheme.loadTable("Content/UI/DT_HudStyle.json")
//     .then(() => Kit.start({ groups: { ...mine, ...UnrealTheme.groups() }, draw(ctx, v, s) { UnrealTheme.use(v); ... } }))
//
// API: configure({ root }), loadClass(path, { className, categories, ini }), loadTable(path), groups(), use(values),
//   get(name, field).
//   get(name, field) returns the tuned value: name is a loaded class ("HudSettings"), a row name ("Default"), or
//   "<file stem>/<RowName>" when two loaded tables share row names; field is the property or flattened field name
//   ("CornerRadius", "Padding/Left").
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
// DataTables have no apply script: write the tuned values into the exported JSON (FLinearColor back through the
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

  // ---- C++ class defaults (loadClass) ----
  // The same rules as apply_unreal.py, which writes the values back: keep the two in step.
  const MEMBERS = { FVector2D: "XY", FVector2f: "XY", FIntPoint: "XY", FVector: "XYZ", FVector3f: "XYZ", FIntVector: "XYZ",
    FMargin: ["Left", "Top", "Right", "Bottom"] };
  const FLOATS = ["float", "double"], INTS = ["int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64", "int"];
  const NAMED = { White: [255, 255, 255, 255], Black: [0, 0, 0, 255], Transparent: [0, 0, 0, 0], Red: [255, 0, 0, 255],
    Green: [0, 255, 0, 255], Blue: [0, 0, 255, 255], Yellow: [255, 255, 0, 255] };
  const classes = []; // { group, note, props: { name: { type, value, category, min, max, options, hint, ini } } }

  /** Comments blanked to spaces (offsets kept), so brackets and declarations can be matched. */
  function stripComments(t) {
    return t.replace(/\/\/[^\n]*|\/\*[\s\S]*?\*\/|"(?:\\.|[^"\\\n])*"/g, m => (m[0] === '"' ? m : m.replace(/[^\n]/g, " ")));
  }
  function close(code, i, o = "(", c = ")") {
    let d = 0;
    for (let j = i; j < code.length; j++) { if (code[j] === o) d++; else if (code[j] === c && --d === 0) return j + 1; }
    return code.length;
  }
  function specifiers(s) {
    const out = {};
    for (const m of s.matchAll(/(\w+)\s*=\s*("([^"]*)"|\(([^()]*)\)|[\w.\-]+)|(\w+)/g)) {
      if (m[5]) out[m[5]] = true;
      else if (m[4] !== undefined) Object.assign(out, specifiers(m[4]));
      else out[m[1]] = m[3] !== undefined ? m[3] : m[2];
    }
    return out;
  }
  function num(s) {
    s = String(s ?? "").trim();
    let m = /^([-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?)f?$/i.exec(s);
    if (m) return Number(m[1]);
    m = /^0x([0-9a-f]+)u?$/i.exec(s);
    return m ? parseInt(m[1], 16) : null;
  }
  function argsOf(e, ctor) {
    e = e.trim();
    if (e.startsWith(ctor)) e = e.slice(ctor.length).trim();
    if (!/^[({][\s\S]*[)}]$/.test(e)) return null;
    const parts = []; let d = 0, cur = "";
    for (const c of e.slice(1, -1)) {
      if ("({".includes(c)) d++; else if (")}".includes(c)) d--;
      if (c === "," && !d) { parts.push(cur.trim()); cur = ""; } else cur += c;
    }
    if (cur.trim()) parts.push(cur.trim());
    return parts;
  }
  const bytesHex = c => "#" + c.map(x => hex2(x / 255)).join("");
  function colourDefault(type, e) {
    let m = /^F(?:Linear)?Color::(\w+)$/.exec(e);
    if (m) return NAMED[m[1]] ? bytesHex(NAMED[m[1]]) : null;
    let inner = type === "FLinearColor" ? argsOf(e, "FLinearColor") : null;
    if (inner && inner.length === 1 && inner[0].startsWith("FColor")) { e = inner[0]; inner = null; }
    if (inner) {
      const v = inner.map(num);
      return (v.length === 3 || v.length === 4) && !v.includes(null) ? "#" + [...v.slice(0, 3).map(srgb), v[3] ?? 1].map(hex2).join("") : null;
    }
    const v = (argsOf(e, "FColor") || [null]).map(num);
    return (v.length === 3 || v.length === 4) && !v.includes(null) ? bytesHex([...v.slice(0, 3), v[3] ?? 255]) : null;
  }
  function valueOf(type, e, enums) {
    const members = MEMBERS[type] && [...MEMBERS[type]];
    if (e == null) return members ? Object.fromEntries(members.map(k => [k, 0])) : type === "bool" ? false
      : FLOATS.includes(type) || INTS.includes(type) ? 0 : null;
    e = e.trim();
    if (type === "bool") return e === "true" ? true : e === "false" ? false : null;
    if (FLOATS.includes(type) || INTS.includes(type)) return num(e);
    if (type === "FLinearColor" || type === "FColor") return colourDefault(type, e);
    if (members) {
      if (/^\w+::Zero(Vector)?$/.test(e)) return Object.fromEntries(members.map(k => [k, 0]));
      let v = (argsOf(e, type) || [null]).map(num);
      if (v.includes(null)) return null;
      if (v.length === 1) v = members.map(() => v[0]);
      if (type === "FMargin" && v.length === 2) v = [v[0], v[1], v[0], v[1]];
      return v.length === members.length ? Object.fromEntries(members.map((k, i) => [k, v[i]])) : null;
    }
    if (enums[type]) { const m = new RegExp(`^${type}::(\\w+)$`).exec(e); return m && enums[type].includes(m[1]) ? m[1] : null; }
    return null;
  }
  function commentAbove(text, at) {
    const above = text.slice(0, at).trimEnd();
    let body = "";
    if (above.endsWith("*/")) body = above.slice(above.lastIndexOf("/*") + 2, -2);
    else {
      const lines = [];
      for (const l of above.split("\n").reverse()) { if (!l.trim().startsWith("//")) break; lines.unshift(l.trim().slice(2)); }
      body = lines.join("\n");
    }
    return body.replace(/^\s*\*+/gm, "").replace(/\s+/g, " ").replace(/^[\s*]+|[\s*]+$/g, "").slice(0, 300);
  }
  function parseHeader(text) {
    const code = stripComments(text), enums = {}, out = [];
    for (const m of code.matchAll(/\benum\s+(?:class\s+)?(\w+)\s*(?::\s*\w+\s*)?\{/g)) {
      const body = code.slice(m.index + m[0].length, close(code, m.index + m[0].length - 1, "{", "}") - 1).replace(/\w+\s*\([^()]*\)/g, "");
      enums[m[1]] = body.split(",").map(x => x.trim().split(/[\s=]/)[0]).filter(Boolean);
    }
    const DECL = /\s*((?:\w+::)*\w+(?:\s*<[^;=]*?>)?)\s+(\w+)\s*(?:=\s*([^;]+?)|(\{[^;]*\}))?\s*;/y;
    for (const m of code.matchAll(/\bUCLASS\s*\(/g)) {
      const specEnd = close(code, m.index + m[0].length - 1), spec = specifiers(code.slice(m.index + m[0].length, specEnd - 1));
      const d = /\s*(?:class|struct)\s+(?:\w+_API\s+)?([UAF])(\w+)\b[^{;]*\{/y;
      d.lastIndex = specEnd;
      const dm = d.exec(code);
      if (!dm) continue;
      const bodyStart = d.lastIndex, bodyEnd = close(code, bodyStart - 1, "{", "}"), props = {};
      const P = /\bUPROPERTY\s*\(/g;
      P.lastIndex = bodyStart;
      for (let p; (p = P.exec(code)) && p.index < bodyEnd;) {
        const sEnd = close(code, P.lastIndex - 1), sText = code.slice(P.lastIndex, sEnd - 1);
        DECL.lastIndex = sEnd;
        const dec = DECL.exec(code);
        if (!dec || !/\b(EditAnywhere|EditDefaultsOnly|Config|GlobalConfig)\b/.test(sText)) continue;
        const ps = specifiers(sText), type = dec[1];
        props[dec[2]] = { type, value: valueOf(type, dec[3] ?? dec[4], enums), category: ps.Category || "",
          config: /\b(Global)?Config\b/.test(sText), min: num(ps.ClampMin ?? ps.UIMin), max: num(ps.UIMax ?? ps.ClampMax),
          options: enums[type] || null, hint: commentAbove(text, p.index), int: INTS.includes(type) || /^FInt/.test(type) };
      }
      out.push({ name: dm[2], config: spec.Config || spec.config || null, props });
    }
    return out;
  }
  /** An ini value (Key=Value) read as the property's type. */
  function iniValue(raw, p) {
    raw = raw.trim();
    if (p.type === "bool") return /^true$/i.test(raw);
    if (FLOATS.includes(p.type) || INTS.includes(p.type)) return num(raw);
    const f = Object.fromEntries([...raw.matchAll(/(\w+)=([-+\d.eE]+)/g)].map(m => [m[1], Number(m[2])]));
    if (MEMBERS[p.type]) return Object.fromEntries([...MEMBERS[p.type]].map(k => [k, f[k] ?? 0]));
    if (p.type === "FLinearColor") return "#" + [srgb(f.R ?? 0), srgb(f.G ?? 0), srgb(f.B ?? 0), f.A ?? 1].map(hex2).join("");
    if (p.type === "FColor") return bytesHex([f.R ?? 0, f.G ?? 0, f.B ?? 0, f.A ?? 255]);
    return raw.replace(/^"|"$/g, "");
  }
  function iniOverrides(text, name) {
    const out = {};
    let inside = false;
    for (const line of text.split(/\r?\n/)) {
      const h = /^\[([^\]]+)\]\s*$/.exec(line);
      if (h) { inside = new RegExp(`^/Script/\\w+\\.${name}$`).test(h[1]); continue; }
      const kv = inside && /^(\w+)=(.*)$/.exec(line);
      if (kv) out[kv[1]] = kv[2];
    }
    return out;
  }
  function slider(value, p) {
    const s = Kit.spec(value);
    const dec = (String(value).split(".")[1] || "").length;
    s.step = p.int ? 1 : dec ? Math.pow(10, -Math.min(dec, 4)) : Math.abs(value) >= 100 ? 1 : 0.1;
    if (p.min != null) s.min = p.min;
    if (p.max != null) s.max = p.max;
    else if (p.min != null && s.max <= p.min) s.max = p.min + Math.max(1, 4 * Math.abs(value));
    s.min = Math.min(s.min, value); s.max = Math.max(s.max, value);
    return s;
  }

  /**
   * Read a C++ header's UCLASS defaults into one group per class (named without its U / A / F prefix, the name
   * apply_unreal.py looks the class up by). Each editable UPROPERTY (EditAnywhere / EditDefaultsOnly / Config) becomes a
   * value in a section named after its Category; struct members are "Prop/X". For a Config class the overrides in
   * Config/Default<Config>.ini (or opts.ini) replace the header defaults. opts.className keeps one class of the header;
   * opts.categories keeps the properties in those Categories ("Telegraph" also keeps "Telegraph|Card").
   */
  async function loadClass(path, opts = {}) {
    const r = await fetch(ROOT + path, { cache: "no-store" });
    if (!r.ok) throw new Error("missing " + path);
    let found = parseHeader(await r.text());
    if (opts.className) found = found.filter(c => [c.name, "U" + c.name, "A" + c.name, "F" + c.name].includes(opts.className));
    if (!found.length) throw new Error(`UnrealTheme: no UCLASS${opts.className ? " " + opts.className : ""} in ${path}`);
    for (const c of found) {
      const iniPath = opts.ini || (c.config ? `Config/Default${c.config}.ini` : null);
      let over = {};
      if (iniPath) {
        const ir = await fetch(ROOT + iniPath, { cache: "no-store" });
        if (ir.ok && ir.status !== 204) over = iniOverrides(await ir.text(), c.name);
      }
      const props = {}, skipped = [];
      const cats = opts.categories;
      for (const [name, p] of Object.entries(c.props)) {
        if (cats && !cats.some(k => p.category === k || p.category.startsWith(k + "|"))) continue;
        const value = name in over && p.config ? iniValue(over[name], p) : p.value;
        if (value == null) { skipped.push(`${p.type} ${name}`); continue; }
        props[name] = { ...p, value, ini: name in over };
      }
      if (skipped.length) console.info(`UnrealTheme: ${c.name}: left out (no literal default, or a type the kit can't tune): ${skipped.join(", ")}`);
      classes.push({ group: c.name, note: path + (iniPath ? ` + ${iniPath}` : ""), props });
    }
  }

  function classGroup(c) {
    const params = {};
    for (const [name, p] of Object.entries(c.props)) {
      const extra = { section: p.category || undefined, hint: (p.ini ? "(from the ini) " : "") + p.hint || undefined };
      if (typeof p.value === "object") for (const [k, x] of Object.entries(p.value)) params[`${name}/${k}`] = { ...slider(x, p), ...extra };
      else if (typeof p.value === "number") params[name] = { ...slider(p.value, p), ...extra };
      else if (p.options) params[name] = { value: p.value, options: p.options, ...extra };
      else params[name] = { ...Kit.spec(p.value), ...extra };
    }
    return { note: c.note, params };
  }

  function groups() {
    const out = {};
    for (const t of tables)
      out[t.group] = { note: t.note, params: Object.fromEntries(Object.entries(t.fields).map(([k, v]) => [k, Kit.spec(v)])) };
    for (const c of classes) out[c.group] = classGroup(c);
    return out;
  }

  function get(row, field) {
    const c = classes.find(c => c.group === row);
    if (c) {
      const [name, member] = field.split("/");
      const p = c.props[name];
      return tuned[c.group]?.[field] ?? (p && (member ? p.value?.[member] : p.value));
    }
    const t = tables.find(t => t.group === `table: ${row}`) || tables.find(t => t.row === row);
    if (!t) return undefined;
    return tuned[t.group]?.[field] ?? t.fields[field];
  }

  function configure(o) { if (o.root) ROOT = o.root; }

  /** Call at the top of draw() so get() sees the tuning panel's values. */
  function use(values) { tuned = values; }

  return { configure, loadTable, loadClass, groups, get, use, tables, classes };
})();
