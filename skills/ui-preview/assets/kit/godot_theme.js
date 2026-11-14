// GodotTheme: a Godot 4 project's Theme in the preview, on top of kit.js.
//
// Reads the project Theme .tres (gui/theme/custom in project.godot, or configure({ theme })) so colours, font sizes,
// fonts and StyleBoxes are the game's own; draws text on Godot's Label metrics, StyleBoxFlat / StyleBoxTexture panels
// the way Godot draws them, and key caps for the input device the preview is set to.
//
// Configure once per project in a small project.js loaded after this file, then on each page:
//   GodotTheme.load().then(() => Kit.start({ groups: { ...mine, ...GodotTheme.themeGroups(["Title", "MyPanel"]) },
//     draw(ctx, v, s) { GodotTheme.use(v); GodotTheme.panel(ctx, GodotTheme.style("MyPanel"), 40, 40, 320, 120); } }));
//
// API
//   configure({ root, theme, fonts, defaultFont, glyphs, cap, capInk, capLetter })
//       root: the project root from the page (default "../../../"). theme: a "res://" Theme to read instead of the
//       project's. fonts: { "res://path/font.ttf": "CssFamily" }, families from project.css. defaultFont: the CSS family
//       for text with no theme font (default "monospace"). glyphs: { device: { action: glyph } }.
//       cap: { height, padding, step, size }. capInk / capLetter: key cap face and letter colours.
//   load() -> Promise          reads the theme, the StyleBox .tres files it points at and their textures.
//   use(values)                call first in draw(): lookups then see the tuning panel's values.
//   themeGroups(names)         tuning-panel groups "theme: <name>". <name> is a StyleBox sub-resource id (keys: its
//                              bg_color, border_color, border_width, corner_radius) or a theme type (keys: its own
//                              colours, constants, font_size, and "<style>/<property>" for each StyleBox it sets).
//   color(type, name = "font_color"), fontSize(type), font(type)   along the base_type chain, like get_theme_*.
//   style(type, name = "panel"), styleBox(id)                      a StyleBox (tuning applied), or null.
//   panel(ctx, box | id | type, x, y, w, h)                        draws a StyleBoxFlat or StyleBoxTexture.
//   dim(ctx, id)               fills the canvas with that StyleBox's bg_color.
//   text(ctx, s, x, y, { type, size, font, color, align, valign }) -> width; width(ctx, s, opts); lineHeight(ctx, opts)
//   wrap(ctx, s, maxWidth, opts) -> lines; paragraph(ctx, s, x, y, maxWidth, opts) -> height used
//   image(ctx, img, x, y, w?, h?)   drawImage on whole pixels.
//   cap(ctx, action, x, y, device, pressed?), capWidth(ctx, action, device), drawCap(ctx, glyph, x, y, pressed?),
//   glyphWidth(ctx, glyph), hints(ctx, [[action, label], ...], x, y, device, { align, gap, ...textOpts })
//   GLYPHS, CAP, theme (the parsed .tres), mixHex(a, b, k)
//
// Not drawn like Godot: StyleBoxFlat skew, border_blend, anti_aliasing = false (edges are always smooth), corner_detail
// 2..7 (drawn as a smooth curve), elliptical inner corners under uneven borders (approximated); StyleBoxTexture
// modulate_color; StyleBoxLine and other StyleBox types (skipped); a theme font's own settings (FontVariation
// spacing or embolden, outlines, shadows): map its path to a CSS family that already looks right.
const GodotTheme = (() => {
  let ROOT = "../../../";
  let THEME = null;
  let FONTS = {};
  let DEFAULT_FONT = "monospace";
  const theme = { props: {}, subs: {}, exts: {}, textures: {} };
  let tuned = {};

  const SIDES = ["left", "top", "right", "bottom"];
  const CORNERS = ["top_left", "top_right", "bottom_right", "bottom_left"];

  function parseValue(raw) {
    raw = raw.trim();
    let m;
    if ((m = raw.match(/^Color\(([^)]+)\)$/))) {
      const c = m[1].split(",").map(Number);
      return "#" + c.map(x => Math.round(Math.min(1, Math.max(0, x)) * 255).toString(16).padStart(2, "0")).join("");
    }
    if ((m = raw.match(/^(?:Vector2i?|Rect2i?)\(([^)]+)\)$/))) return m[1].split(",").map(Number);
    if ((m = raw.match(/^SubResource\("([^"]+)"\)$/))) return { sub: m[1] };
    if ((m = raw.match(/^ExtResource\("([^"]+)"\)$/))) return { ext: m[1] };
    if ((m = raw.match(/^&?"(.*)"$/))) return m[1];
    if (/^-?[\d.]+(e-?\d+)?$/.test(raw)) return Number(raw);
    if (raw === "true" || raw === "false") return raw === "true";
    return raw;
  }

  const attrs = line => Object.fromEntries([...line.matchAll(/(\w+)="([^"]*)"/g)].map(m => [m[1], m[2]]));

  // A Godot text resource: its type, [ext_resource]s, [sub_resource]s and the [resource] itself.
  function parseTres(text) {
    const out = { type: null, exts: {}, subs: {}, props: {} };
    let current = null;
    for (const line of text.split(/\r?\n/)) {
      let m;
      if (line.startsWith("[gd_resource")) out.type = attrs(line).type;
      else if (line.startsWith("[ext_resource")) { const a = attrs(line); out.exts[a.id] = a.path; current = null; }
      else if (line.startsWith("[sub_resource")) { const a = attrs(line); current = out.subs[a.id] = { type: a.type }; }
      else if (line.startsWith("[resource]")) current = out.props;
      else if (current && (m = line.match(/^([^=]+?) = (.+)$/))) current[m[1]] = parseValue(m[2]);
    }
    return out;
  }

  async function fetchText(path) {
    const r = await fetch(ROOT + path.replace(/^res:\/\//, ""), { cache: "no-store" });
    if (!r.ok) throw new Error("GodotTheme: missing " + path);
    return r.text();
  }

  function loadImage(path) {
    return new Promise(ok => {
      const img = new Image();
      img.onload = () => ok(img);
      img.onerror = () => { console.warn("GodotTheme: missing texture " + path); ok(null); };
      img.src = ROOT + path.replace(/^res:\/\//, "");
    });
  }

  async function load() {
    const path = THEME ?? (await fetchText("project.godot").catch(() => "")).match(/^theme\/custom="([^"]+)"/m)?.[1];
    if (!path) {
      const msg = `GodotTheme: no theme to read. Set Project Settings > GUI > Theme > Custom (gui/theme/custom), or call ` +
        `GodotTheme.configure({ theme: "res://path/theme.tres" }). Looked for ${ROOT}project.godot.`;
      console.error(msg);
      throw new Error(msg);
    }
    Object.assign(theme, parseTres(await fetchText(path)));
    for (const box of Object.values(theme.subs)) {
      if (box.type !== "StyleBoxTexture" || !box.texture?.ext) continue;
      box.texture = theme.exts[box.texture.ext];
      theme.textures[box.texture] ??= await loadImage(box.texture);
    }
    for (const [id, p] of Object.entries(theme.exts)) {
      if (!p?.endsWith(".tres")) continue;
      const res = parseTres(await fetchText(p).catch(e => (console.warn(e.message), "")));
      if (res.type === "StyleBoxFlat") theme.subs["ext:" + id] = { type: res.type, ...res.props };
      else if (res.type === "StyleBoxTexture") {
        const texture = res.exts[res.props.texture?.ext];
        theme.subs["ext:" + id] = { type: res.type, ...res.props, texture };
        if (texture) theme.textures[texture] ??= await loadImage(texture);
      }
    }
  }

  // Theme lookup along the base_type chain, the tuning panel first at each step.
  function raw(type, kind, name) {
    for (let t = type; t; t = theme.props[`${t}/base_type`]) {
      const v = tuned[`theme: ${t}`]?.[name] ?? theme.props[`${t}/${kind}/${name}`];
      if (v !== undefined) return v;
    }
  }

  // Godot's own defaults where the theme says nothing: Label font_color white, size 16, line_spacing 3.
  function color(type, name = "font_color") { return raw(type, "colors", name) ?? raw("Label", "colors", name) ?? "#ffffffff"; }
  function fontSize(type) { return raw(type, "font_sizes", "font_size") ?? theme.props.default_font_size ?? 16; }
  function font(type) {
    const ref = raw(type, "fonts", "font") ?? theme.props.default_font;
    return FONTS[theme.exts[ref?.ext]] ?? DEFAULT_FONT;
  }

  // The panel tunes border_width and corner_radius for all sides at once.
  function tune(box, t) {
    const out = { ...box, ...t };
    if (t.border_width !== undefined) for (const s of SIDES) out[`border_width_${s}`] = t.border_width;
    if (t.corner_radius !== undefined) for (const c of CORNERS) out[`corner_radius_${c}`] = t.corner_radius;
    return out;
  }

  function styleBox(id) {
    const s = theme.subs[id];
    return s ? tune(s, tuned[`theme: ${id}`] || {}) : null;
  }

  /** The StyleBox a theme type uses for a state, e.g. style("MyButton", "focus"), with "<state>/<key>" tuning on top. */
  function style(type, name = "panel") {
    for (let t = type; t; t = theme.props[`${t}/base_type`]) {
      const ref = theme.props[`${t}/styles/${name}`];
      if (!ref) continue;
      const box = styleBox(ref.sub ?? "ext:" + ref.ext);
      const prefix = name + "/";
      const own = Object.entries(tuned[`theme: ${t}`] || {}).filter(([k]) => k.startsWith(prefix));
      return box && tune(box, Object.fromEntries(own.map(([k, v]) => [k.slice(prefix.length), v])));
    }
    return null;
  }

  // ----- drawing

  function metrics(ctx) {
    const m = ctx.measureText("Hg");
    return { ascent: m.fontBoundingBoxAscent, descent: m.fontBoundingBoxDescent };
  }

  function setFont(ctx, opts) {
    const type = opts.type || "Label";
    const size = opts.size ?? fontSize(type);
    ctx.font = `${size}px ${opts.font || font(type)}, monospace`; // monospace while a family isn't loaded
    return size;
  }

  /** Text like a Godot Label: valign "top" puts the ascent+descent box's top at y, "middle" centres it, else bottom. */
  function text(ctx, s, x, y, opts = {}) {
    setFont(ctx, opts);
    const { ascent, descent } = metrics(ctx);
    const w = ctx.measureText(s).width;
    const valign = opts.valign || "top";
    const baseline = valign === "top" ? y + ascent : valign === "middle" ? y - (ascent + descent) / 2 + ascent : y - descent;
    const left = opts.align === "center" ? x - w / 2 : opts.align === "right" ? x - w : x;
    ctx.fillStyle = opts.color || color(opts.type || "Label");
    ctx.fillText(s, Math.round(left), Math.round(baseline));
    return w;
  }

  function width(ctx, s, opts = {}) {
    setFont(ctx, opts);
    return ctx.measureText(s).width;
  }

  function lineHeight(ctx, opts = {}) {
    setFont(ctx, opts);
    const { ascent, descent } = metrics(ctx);
    return ascent + descent + (raw(opts.type || "Label", "constants", "line_spacing") ?? 3);
  }

  function wrap(ctx, s, maxWidth, opts = {}) {
    setFont(ctx, opts);
    const lines = [];
    for (const para of s.split("\n")) {
      let line = "";
      for (const word of para.split(" ")) {
        const next = line ? line + " " + word : word;
        if (line && ctx.measureText(next).width > maxWidth) { lines.push(line); line = word; } else line = next;
      }
      lines.push(line);
    }
    return lines;
  }

  /** Wrapped text from (x, y) down; returns the height used. */
  function paragraph(ctx, s, x, y, maxWidth, opts = {}) {
    const lh = lineHeight(ctx, opts);
    const lines = wrap(ctx, s, maxWidth, opts);
    lines.forEach((line, i) => text(ctx, line, opts.align === "center" ? x + maxWidth / 2 : x, y + i * lh, opts));
    return lines.length * lh;
  }

  // A rectangle with per-corner radii [tl, tr, br, bl], rounded, or cut straight (corner_detail 1), as a sub-path.
  function shape(ctx, x, y, w, h, [tl, tr, br, bl], cut) {
    const corner = (cx, cy, ex, ey, r) => (cut ? ctx.lineTo(ex, ey) : ctx.arcTo(cx, cy, ex, ey, r));
    ctx.moveTo(x + tl, y);
    ctx.lineTo(x + w - tr, y); corner(x + w, y, x + w, y + tr, tr);
    ctx.lineTo(x + w, y + h - br); corner(x + w, y + h, x + w - br, y + h, br);
    ctx.lineTo(x + bl, y + h); corner(x, y + h, x, y + h - bl, bl);
    ctx.lineTo(x, y + tl); corner(x, y, x + tl, y, tl);
    ctx.closePath();
  }

  /** A theme StyleBox: a resolved box, a StyleBox id, or a theme type (its "panel" style). */
  function panel(ctx, box, x, y, w, h) {
    if (typeof box === "string") box = styleBox(box) || style(box);
    if (!box) return;
    const [el, et, er, eb] = SIDES.map(s => box[`expand_margin_${s}`] ?? 0);
    x = Math.round(x - el); y = Math.round(y - et); w = Math.round(w + el + er); h = Math.round(h + et + eb);
    if (box.type === "StyleBoxTexture") nineSlice(ctx, box, x, y, w, h);
    else if (box.type === "StyleBoxFlat") flat(ctx, box, x, y, w, h);
  }

  // Godot's StyleBoxFlat defaults stand in for lines the .tres leaves out.
  function flat(ctx, b, x, y, w, h) {
    const [bl, bt, br, bb] = SIDES.map(s => b[`border_width_${s}`] ?? 0);
    let r = CORNERS.map(c => b[`corner_radius_${c}`] ?? 0);
    const fit = Math.min(1, ...[[0, 1, w], [3, 2, w], [0, 3, h], [1, 2, h]].map(([a, c, len]) => (r[a] + r[c] > 0 ? len / (r[a] + r[c]) : 1)));
    r = r.map(v => v * fit);
    const cut = (b.corner_detail ?? 8) <= 1;
    if ((b.shadow_size ?? 0) > 0) {
      // Draw the shape far off-canvas and let its canvas shadow land in place.
      const [ox, oy] = b.shadow_offset ?? [0, 0], far = 100000, m = ctx.getTransform();
      ctx.save();
      ctx.shadowColor = b.shadow_color ?? "#00000099";
      ctx.shadowBlur = b.shadow_size * m.a;
      ctx.shadowOffsetX = (far + ox) * m.a; ctx.shadowOffsetY = oy * m.d;
      ctx.beginPath(); shape(ctx, x - far, y, w, h, r, cut);
      ctx.fillStyle = "#000"; ctx.fill();
      ctx.restore();
    }
    const ix = x + bl, iy = y + bt, iw = w - bl - br, ih = h - bt - bb;
    const ri = [r[0] - Math.max(bl, bt), r[1] - Math.max(br, bt), r[2] - Math.max(br, bb), r[3] - Math.max(bl, bb)].map(v => Math.max(0, v));
    if (bl || bt || br || bb) {
      ctx.beginPath(); shape(ctx, x, y, w, h, r, cut);
      if (iw > 0 && ih > 0) shape(ctx, ix, iy, iw, ih, ri, cut);
      ctx.fillStyle = b.border_color ?? "#ccccccff"; ctx.fill("evenodd");
    }
    if (b.draw_center !== false && iw > 0 && ih > 0) {
      ctx.beginPath(); shape(ctx, ix, iy, iw, ih, ri, cut);
      ctx.fillStyle = b.bg_color ?? "#999999ff"; ctx.fill();
    }
  }

  // One slice of a 9-slice; per axis, 0 = stretch, 1 = tile, 2 = tile_fit (Godot's axis_stretch_*).
  function slice(ctx, img, sx, sy, sw, sh, dx, dy, dw, dh, mh, mv) {
    if (sw <= 0 || sh <= 0 || dw <= 0 || dh <= 0) return;
    const step = (mode, s, d) => (mode === 1 ? s : mode === 2 ? d / Math.max(1, Math.round(d / s)) : d);
    const tw = step(mh, sw, dw), th = step(mv, sh, dh);
    for (let yy = 0; yy < dh - 0.01; yy += th) for (let xx = 0; xx < dw - 0.01; xx += tw) {
      const pw = Math.min(tw, dw - xx), ph = Math.min(th, dh - yy);
      ctx.drawImage(img, sx, sy, sw * pw / tw, sh * ph / th, dx + xx, dy + yy, pw, ph);
    }
  }

  function nineSlice(ctx, b, x, y, w, h) {
    const img = theme.textures[b.texture];
    if (!img) return;
    const [rx, ry, rw, rh] = b.region_rect?.[2] > 0 ? b.region_rect : [0, 0, img.width, img.height];
    const [l, t, r, bm] = SIDES.map(s => Math.round(b[`texture_margin_${s}`] ?? 0));
    const sx = [rx, rx + l, rx + rw - r], sw = [l, rw - l - r, r], sy = [ry, ry + t, ry + rh - bm], sh = [t, rh - t - bm, bm];
    const dx = [x, x + l, x + w - r], dw = [l, w - l - r, r], dy = [y, y + t, y + h - bm], dh = [t, h - t - bm, bm];
    const mh = b.axis_stretch_horizontal ?? 0, mv = b.axis_stretch_vertical ?? 0;
    for (let j = 0; j < 3; j++) for (let i = 0; i < 3; i++) {
      if (i === 1 && j === 1 && b.draw_center === false) continue;
      slice(ctx, img, sx[i], sy[j], sw[i], sh[j], dx[i], dy[j], dw[i], dh[j], i === 1 ? mh : 0, j === 1 ? mv : 0);
    }
  }

  /** Fills the whole canvas with a StyleBox's bg_color (a screen dim behind a menu). */
  function dim(ctx, id) {
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = styleBox(id)?.bg_color ?? "#00000080";
    ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height);
    ctx.restore();
  }

  function image(ctx, img, x, y, w, h) {
    ctx.drawImage(img, Math.round(x), Math.round(y), Math.round(w ?? img.width), Math.round(h ?? img.height));
  }

  // ----- input glyphs per device: action -> key text, ["face", letter | cross | circle | square | triangle] or
  // ["pill", label]. Replace with the game's bindings in configure({ glyphs }).

  let GLYPHS = {
    keyboard: { ui_accept: "ENTER", ui_cancel: "ESC", ui_pause: "ESC" },
    xbox: { ui_accept: ["face", "A"], ui_cancel: ["face", "B"], ui_pause: ["pill", "MENU"] },
    playstation: { ui_accept: ["face", "cross"], ui_cancel: ["face", "circle"], ui_pause: ["pill", "OPTIONS"] },
  };
  let CAP = { height: 28, padding: 8, step: 4, size: 16, ink: "#e8e8e8", letter: "#202020" };

  function configure(o) {
    if (o.root) ROOT = o.root;
    if (o.theme) THEME = o.theme;
    if (o.fonts) FONTS = o.fonts;
    if (o.defaultFont) DEFAULT_FONT = o.defaultFont;
    if (o.glyphs) GLYPHS = o.glyphs;
    CAP = { ...CAP, ...o.cap, ...(o.capInk && { ink: o.capInk }), ...(o.capLetter && { letter: o.capLetter }) };
  }

  function capWidth(ctx, action, input) { return glyphWidth(ctx, GLYPHS[input][action]); }

  function glyphWidth(ctx, g) {
    if (Array.isArray(g) && g[0] === "face") return CAP.height;
    return width(ctx, Array.isArray(g) ? g[1] : g, { size: CAP.size }) + CAP.padding * 2;
  }

  /** One key cap for an action on a device. */
  function cap(ctx, action, x, y, input, pressed = false) { return drawCap(ctx, GLYPHS[input][action], x, y, pressed); }

  /** A glyph: a key's text ("SPACE"), ["face", "A" | "cross" | ...] or ["pill", "LB"]: a pale cap on its shadow. */
  function drawCap(ctx, g, x, y, pressed = false) {
    const ink = CAP.ink, shade = mixHex(ink, "#000000", 0.5), letter = CAP.letter;
    const dip = pressed ? CAP.step : 0, w = glyphWidth(ctx, g);
    if (Array.isArray(g) && g[0] === "face") {
      const r = CAP.height / 2, cx = x + r;
      if (!pressed) { ctx.fillStyle = shade; ctx.beginPath(); ctx.arc(cx, y + r + CAP.step, r, 0, 7); ctx.fill(); }
      ctx.fillStyle = ink; ctx.beginPath(); ctx.arc(cx, y + r + dip, r, 0, 7); ctx.fill();
      const cy = y + r + dip;
      ctx.strokeStyle = letter; ctx.fillStyle = letter; ctx.lineWidth = 3;
      if (g[1] === "cross") { ctx.beginPath(); ctx.moveTo(cx - 6, cy - 6); ctx.lineTo(cx + 6, cy + 6); ctx.moveTo(cx + 6, cy - 6); ctx.lineTo(cx - 6, cy + 6); ctx.stroke(); }
      else if (g[1] === "circle") { ctx.beginPath(); ctx.arc(cx, cy, 6, 0, 7); ctx.stroke(); }
      else if (g[1] === "square") ctx.strokeRect(cx - 6, cy - 6, 12, 12);
      else if (g[1] === "triangle") { ctx.beginPath(); ctx.moveTo(cx, cy - 7); ctx.lineTo(cx + 7, cy + 5); ctx.lineTo(cx - 7, cy + 5); ctx.closePath(); ctx.stroke(); }
      else text(ctx, g[1], cx, cy, { size: CAP.size, align: "center", valign: "middle", color: letter });
    } else {
      if (!pressed) { ctx.fillStyle = shade; ctx.fillRect(x, y + CAP.step, w, CAP.height); }
      ctx.fillStyle = ink; ctx.fillRect(x, y + dip, w, CAP.height);
      text(ctx, Array.isArray(g) ? g[1] : g, x + w / 2, y + dip + CAP.height / 2, { size: CAP.size, align: "center", valign: "middle", color: letter });
    }
    return w;
  }

  /** A row of [cap] LABEL hints, e.g. along the bottom of a menu. align: left | center | right of x. */
  function hints(ctx, items, x, y, input, opts = {}) {
    const { align, gap = 32, ...label } = opts, labelGap = 10;
    const total = items.reduce((sum, [action, l]) => sum + capWidth(ctx, action, input) + labelGap + width(ctx, l, label), 0) + gap * (items.length - 1);
    let cx = align === "center" ? x - total / 2 : align === "right" ? x - total : x;
    for (const [action, l] of items) {
      cx += cap(ctx, action, cx, y, input) + labelGap;
      cx += text(ctx, l, cx, y + CAP.height / 2 + 2, { ...label, valign: "middle" }) + gap;
    }
    return total;
  }

  function mixHex(a, b, k) {
    const pa = [1, 3, 5].map(i => parseInt(a.slice(i, i + 2), 16)), pb = [1, 3, 5].map(i => parseInt(b.slice(i, i + 2), 16));
    return "#" + pa.map((x, i) => Math.round(x + (pb[i] - x) * k).toString(16).padStart(2, "0")).join("");
  }

  // The keys a StyleBoxFlat shows in the panel: only what its .tres sets, so applying an untouched box changes nothing.
  function boxParams(box, prefix = "") {
    const p = {};
    if (box.type !== "StyleBoxFlat") return p;
    for (const key of ["bg_color", "border_color"]) if (box[key]) p[prefix + key] = { value: box[key] };
    const bw = box.border_width_left, cr = box.corner_radius_top_left;
    if (bw !== undefined) p[prefix + "border_width"] = { value: bw, min: 0, max: Math.max(8, bw * 2), step: 1, unit: "px" };
    if (cr !== undefined) p[prefix + "corner_radius"] = { value: cr, min: 0, max: Math.max(32, cr * 2), step: 1, unit: "px" };
    return p;
  }

  /** Tuning-panel groups for these theme names: StyleBox sub-resource ids or theme types. */
  function themeGroups(names) {
    const groups = {};
    for (const name of names) {
      const sub = theme.subs[name];
      let params = {};
      if (sub) params = boxParams(sub);
      else for (const [k, v] of Object.entries(theme.props)) {
        if (!k.startsWith(name + "/")) continue;
        const [kind, prop] = k.slice(name.length + 1).split("/");
        if (kind === "colors") params[prop] = { value: v };
        else if (kind === "font_sizes" && prop === "font_size") params.font_size = { value: v, min: 8, max: Math.max(16, v * 4), step: 1, unit: "px" };
        else if (kind === "constants") params[prop] = { value: v, min: Math.min(0, v), max: Math.max(16, v * 4), step: 1 };
        else if (kind === "styles" && theme.subs[v?.sub]) Object.assign(params, boxParams(theme.subs[v.sub], prop + "/"));
      }
      if (!Object.keys(params).length) console.warn(`GodotTheme: nothing to tune in "${name}" (not a StyleBoxFlat id or a theme type with values)`);
      groups[`theme: ${name}`] = { note: sub ? "theme stylebox" : "theme type", params };
    }
    return groups;
  }

  /** Call at the top of draw() so lookups see the tuning panel's values. */
  function use(values) {
    tuned = values;
  }

  return {
    configure, load, use, themeGroups, color, font, fontSize, style, styleBox, text, width, wrap, paragraph, lineHeight,
    panel, dim, image, cap, capWidth, drawCap, glyphWidth, hints, mixHex, theme,
    get GLYPHS() { return GLYPHS; },
    get CAP() { return CAP; },
  };
})();
