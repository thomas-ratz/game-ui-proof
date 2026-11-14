#!/usr/bin/env python3
"""Write a ui-preview spec (<mockups>/<feature>/values.json) into a Godot 4 project.

Usage, from the project root:
    python docs/mockups/kit/apply_godot.py <feature | path/to/values.json>
        [--mockups docs/mockups] [--theme path/to/theme.tres] [--write]

Dry run by default: prints, per file, each change as `old → new`, the keys that
have no export yet, and a summary. --write applies the changes.

The theme is project.godot's gui/theme/custom unless --theme names another.

Where each group of values.json goes:
  "theme: X"        X is a StyleBoxFlat / StyleBoxTexture sub_resource id in the theme:
                    its properties (border_width and corner_radius fan out to all four
                    sides/corners). Otherwise X is a theme type: colours -> X/colors/<key>,
                    font_size -> X/font_sizes/font_size, other numbers -> X/constants/<key>,
                    and "<style>/<property>" -> that property of the StyleBox sub_resource
                    X/styles/<style> points at.
  "X.gdshader"      the one X.gdshader in the project: each key is a uniform whose default
                    is rewritten (colours as vec4 / vec3 floats, by the uniform's type).
                    .tscn / .tres that set shader_parameter/<key> for a changed uniform are
                    listed to check. A name matching no file or several is listed, not guessed.
  "...uniforms"     skipped and listed: uniforms set from code at runtime.
  anything else     a script class: the default of each [Export] property or field in
                    <Group>.cs, else of each @export var <snake_key> in <snake_group>.gd.

Values are numbers, booleans, strings or colours "#rrggbbaa". Colours compare at
8-bit precision, so Color(1, 0.71, 0.2, 1) already is #ffb533ff. Group and key names
must be identifiers (letters, digits, _ and /); anything else is rejected unread.
A default that isn't a plain literal (an expression, an unknown named colour) is
listed to do by hand, never overwritten.
"""
import argparse
import codecs
import json
import math
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_/]*")
# Godot's named colours that are certain; any other Colors.X / Color.X is left to do by hand.
NAMED_COLORS = {"white": (255, 255, 255, 255), "black": (0, 0, 0, 255), "transparent": (255, 255, 255, 0),
                "red": (255, 0, 0, 255), "green": (0, 255, 0, 255), "blue": (0, 0, 255, 255),
                "yellow": (255, 255, 0, 255), "cyan": (0, 255, 255, 255), "magenta": (255, 0, 255, 255)}

BOX_TYPES = ("StyleBoxFlat", "StyleBoxTexture")
STYLEBOX_FANOUT = {
    "border_width": [f"border_width_{s}" for s in ("left", "top", "right", "bottom")],
    "corner_radius": [f"corner_radius_{c}" for c in ("top_left", "top_right", "bottom_right", "bottom_left")],
}
STYLEBOX_FLOATS = ("content_margin_", "expand_margin_", "texture_margin_", "anti_aliasing_size")
STYLEBOX_INTS = ("border_width", "corner_radius", "axis_stretch_", "corner_detail", "shadow_size")

CS_KINDS = {"float": "float", "single": "float", "double": "double", "int": "int", "long": "int",
            "short": "int", "byte": "int", "uint": "int", "bool": "bool", "boolean": "bool",
            "string": "string", "color": "color"}
GD_KINDS = {"float": "float", "int": "int", "bool": "bool", "String": "string", "StringName": "string", "Color": "color"}

EXPORT_ATTR = re.compile(r"[\[,]\s*Export\b")  # [Export] / [Export(...)], not [ExportGroup]
GD_EXPORT = r"@export(?!_group|_subgroup|_category)\w*"
GD_EXPORT_LINE = re.compile(rf"\s*{GD_EXPORT}(?:\([^)]*\))?\s*")  # an @export alone on the line above a var
PROP = re.compile(r"^([^\s=\[][^=]*?) = (.*)$")
STRING = r'"(?:[^"\\]|\\.)*"'
UNIFORM = re.compile(r"\s*(?:instance\s+)?uniform\s+(?:(?:lowp|mediump|highp)\s+)?(?P<type>\w+)\s+(?P<name>\w+)\s*"
                     r"(?::[^=;]*)?(?:=\s*(?P<val>[^;]*?)\s*)?;")
NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


# ---- values -------------------------------------------------------------------------------

def parse_hex(s):
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})([0-9a-fA-F]{2})?", s.strip()) if isinstance(s, str) else None
    if not m:
        return None
    h = m.group(1) + (m.group(2) or "ff")
    return tuple(int(h[i:i + 2], 16) for i in range(0, 8, 2))


def to_hex(rgba):
    return "#" + "".join(f"{b:02x}" for b in rgba)


def to_byte(x):
    return max(0, min(255, int(x * 255 + 0.5)))


def gfloat(x):
    # Godot writes colour channels with 4 significant digits: 0.7098, 0.07059.
    return f"{x:.4g}"


def num(x):
    return str(int(x)) if float(x).is_integer() else repr(float(x))


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def color_bytes(text):
    """The colour a .tres / C# / GDScript literal stands for, or None if it's an expression."""
    text = text.strip()
    m = re.fullmatch(r'(?:new\s*(?:Color)?|Color)\s*\(\s*"(#?[0-9a-fA-F]{6,8})"\s*\)', text)
    if m:
        return parse_hex(m.group(1))
    m = re.fullmatch(r"(?:new\s*(?:Color)?|Color)\s*\(([^()\"]*)\)", text)
    if m:
        try:
            ch = [float(p.strip().rstrip("fFdD")) for p in m.group(1).split(",")]
        except ValueError:
            return None
        if len(ch) == 3:
            ch.append(1.0)
        return tuple(to_byte(c) for c in ch) if len(ch) == 4 else None
    m = re.fullmatch(r"Colors?\.(\w+)", text)
    return NAMED_COLORS.get(m.group(1).lower()) if m else None


def parse_literal(kind, text):
    """The value a script default stands for (None: unreadable); no initializer means the type's default."""
    if text is None:
        return {"color": (0, 0, 0, 0), "bool": False, "string": ""}.get(kind, 0.0)
    text = text.strip()
    if kind == "color":
        return color_bytes(text)
    if kind == "bool":
        return {"true": True, "false": False}.get(text)
    if kind == "string":
        m = re.fullmatch(STRING, text)
        named = {"n": "\n", "r": "\r", "t": "\t"}
        unescape = lambda e: chr(int(e[2:], 16)) if e[1] == "u" else named.get(e[1], e[1])
        return re.sub(r"\\u[0-9a-fA-F]{4}|\\.", lambda e: unescape(e.group()), text[1:-1]) if m else None
    try:
        return float(text.rstrip("fFdDmM"))
    except ValueError:
        return None


def same(kind, old, value):
    if kind == "color":
        return old == parse_hex(value)
    if kind in ("float", "double", "int"):
        return abs(old - value) < 1e-6
    return old == value


def fits(kind, value):
    if kind == "color":
        return parse_hex(value) is not None
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "string":
        return isinstance(value, str)
    return is_number(value) and (kind != "int" or float(value).is_integer())


def quote(s):
    """A one-line C# / GDScript string literal: quotes, backslashes and control characters escaped."""
    named = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + re.sub("[\x00-\x1f\x7f\u2028\u2029]", lambda m: named.get(m.group(), f"\\u{ord(m.group()):04x}"), s) + '"'


# ---- files --------------------------------------------------------------------------------

class Doc:
    """A text file edited line by line, written back with its own line endings and BOM."""

    def __init__(self, path):
        raw = path.read_bytes()
        self.path, self.bom = path, raw.startswith(codecs.BOM_UTF8)
        text = raw[3 if self.bom else 0:].decode("utf-8")
        self.eol = "\r\n" if "\r\n" in text else "\n"
        self.lines = re.split(r"\r?\n", text)
        self.final_eol = self.lines[-1] == ""
        if self.final_eol:
            self.lines.pop()
        self.dirty = False

    def save(self):
        text = self.eol.join(self.lines) + (self.eol if self.final_eol else "")
        self.path.write_bytes((codecs.BOM_UTF8 if self.bom else b"") + text.encode("utf-8"))


class Report:
    def __init__(self):
        self.files = defaultdict(lambda: {"changes": [], "same": 0, "missing": [], "notes": [], "props": []})
        self.notes = []
        self.no_script = 0
        self.rejected = 0

    def change(self, path, label, old, new):
        self.files[path]["changes"].append(f"{label}: {old} → {new}" if old is not None else f"{label}: + {new} (added)")

    def print(self, write, overrides):
        totals = defaultdict(int)
        for path, r in self.files.items():
            print(path)
            for line in r["changes"] + r["notes"]:
                print("  " + line)
            if r["missing"]:
                print("  not found: " + ", ".join(r["missing"]))
            print(f"  {r['same']} unchanged" if r["changes"] or r["notes"] or r["missing"] else "  no change")
            for k in ("changes", "missing", "notes"):
                totals[k] += len(r[k])
            totals["same"] += r["same"]
        for note in self.notes:
            print(note)
        check = ("scene overrides to check: " + "; ".join(overrides) + ". ") if overrides else ""
        print(f"\n{totals['changes']} changes, {totals['same']} unchanged, {totals['missing']} not found, "
              f"{self.no_script} with no file, {self.rejected} rejected, "
              f"{totals['notes']} to do by hand. {check}" + ("Written." if write else "Dry run: --write applies."))


# ---- theme ----------------------------------------------------------------------------------

def section(lines, header):
    end = header + 1
    while end < len(lines) and not lines[end].startswith("["):
        end += 1
    while end > header + 1 and not lines[end - 1].strip():
        end -= 1
    return header + 1, end


def get_prop(doc, header, key):
    start, end = section(doc.lines, header)
    for i in range(start, end):
        m = PROP.match(doc.lines[i])
        if m and m.group(1) == key:
            return m.group(2)
    return None


def set_prop(doc, header, key, new, equal):
    """Set `key = new` in the section at `header` (added at its end if absent). (old, new) on change, None if equal."""
    start, end = section(doc.lines, header)
    for i in range(start, end):
        m = PROP.match(doc.lines[i])
        if m and m.group(1) == key:
            if equal(m.group(2)):
                return None
            doc.lines[i] = f"{key} = {new}"
            return m.group(2), new
    doc.lines.insert(end, f"{key} = {new}")
    return None, new


def theme_literal(value, float_key=False):
    """(text, equal) for a theme value, or None when it can't go in a theme."""
    rgba = parse_hex(value)
    if rgba:
        return "Color(" + ", ".join(gfloat(b / 255) for b in rgba) + ")", lambda old: color_bytes(old) == rgba
    if isinstance(value, bool):
        text = "true" if value else "false"
        return text, lambda old: old.strip() == text
    if is_number(value):
        text = repr(float(value)) if float_key else num(value)

        def equal(old):
            try:
                return abs(float(old) - value) < 1e-6
            except ValueError:
                return False
        return text, equal
    return None


def find_box(doc, box_id):
    return next((i for i, l in enumerate(doc.lines) if l.startswith("[sub_resource") and f'id="{box_id}"' in l
                 and any(f'type="{t}"' in l for t in BOX_TYPES)), None)


def resource_header(doc):
    return next(i for i, l in enumerate(doc.lines) if l.startswith("[resource]"))


def apply_theme(doc, name, values, rep, path):
    notes = rep.files[path]["notes"]

    def put(where, key, props, value, header, int_only, float_key=False):
        if int_only and is_number(value) and not float(value).is_integer():
            notes.append(f"{where} {key}: {value} must be a whole number")
            return
        lit = theme_literal(value, float_key)
        if not lit:
            notes.append(f"{where} {key}: {value!r} isn't a colour, number or bool")
            return
        for prop in props:
            result = set_prop(doc, header(), prop, *lit)  # header() again: an insertion moves the lines below
            if result:
                doc.dirty = True
                rep.change(path, f"{where} {prop}", *result)
            else:
                rep.files[path]["same"] += 1

    def put_box(box_id, key, value, where):
        if "/" in key:
            notes.append(f"{where} {key}: no such StyleBox property")
            return
        put(where, key, STYLEBOX_FANOUT.get(key, [key]), value, lambda: find_box(doc, box_id),
            key.startswith(STYLEBOX_INTS), key.startswith(STYLEBOX_FLOATS))

    own_box = find_box(doc, name) is not None
    for key, value in values.items():
        if own_box:
            put_box(name, key, value, f"[{name}]")
        elif "/" in key:
            style, prop = key.split("/", 1)
            ref = get_prop(doc, resource_header(doc), f"{name}/styles/{style}")
            m = re.fullmatch(r'SubResource\("([^"]+)"\)', ref.strip()) if ref else None
            if m and find_box(doc, m.group(1)) is not None:
                put_box(m.group(1), prop, value, f"[{name}] styles/{style} = {m.group(1)}:")
            elif ref:
                notes.append(f"[{name}] {key}: styles/{style} is {ref.strip()}, set it there by hand to {value!r}")
            else:
                rep.files[path]["missing"].append(f"{name}/styles/{style}")
        elif parse_hex(value):
            put(f"[{name}]", key, [f"{name}/colors/{key}"], value, lambda: resource_header(doc), True)
        elif is_number(value):
            prop = f"{name}/font_sizes/font_size" if key == "font_size" else f"{name}/constants/{key}"
            put(f"[{name}]", key, [prop], value, lambda: resource_header(doc), True)
        else:
            notes.append(f"[{name}] {key}: {value!r} has no place in a theme type")


# ---- scripts --------------------------------------------------------------------------------

def snake(name):
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)).lower()


def find_cs(lines, key):
    # Any access level (or none): Godot exports private fields and properties too.
    decl = re.compile(rf"(?P<type>[\w.]+\??)\s+{re.escape(key)}\b(?=\s*[{{=;])")
    for i, line in enumerate(lines):
        m = decl.search(line)
        if not m:
            continue
        exported = EXPORT_ATTR.search(line[:m.start()])
        j = i - 1
        while not exported and j >= 0 and lines[j].strip().startswith("["):
            exported = EXPORT_ATTR.search(lines[j])
            j -= 1
        if exported:
            return i, m
    return None


def cs_literal(kind, value, current):
    if kind == "color":
        rgba = parse_hex(value)
        if current and re.fullmatch(r"new\s*(?:Color\s*)?\([^\"]*\)", current.strip()):
            return "new Color(" + ", ".join(gfloat(b / 255) + "f" for b in rgba) + ")"
        return f'new Color("{to_hex(rgba)}")'
    if kind == "bool":
        return "true" if value else "false"
    if kind == "string":
        return quote(value)
    return num(value) + ("f" if kind == "float" else "")


def apply_cs(doc, values, rep, path):
    for key, value in values.items():
        hit = find_cs(doc.lines, key)
        if not hit:
            rep.files[path]["missing"].append(key)
            continue
        i, m = hit
        line, ctype = doc.lines[i], m.group("type")
        kind = CS_KINDS.get(ctype.rstrip("?").split(".")[-1].lower())
        if not kind:
            rep.files[path]["notes"].append(f"{key}: {ctype} isn't handled, set it by hand to {value!r}")
            continue
        if not fits(kind, value):
            rep.files[path]["notes"].append(f"{key}: {value!r} doesn't fit {ctype}")
            continue
        acc = re.match(r"\s*\{\s*get;\s*(?:\w+\s+)?(?:set|init);\s*\}", line[m.end():])
        pos = m.end() + (acc.end() if acc else 0)
        init = re.match(rf"\s*=\s*(?P<val>(?:{STRING}|[^;\"])*?)\s*;", line[pos:])
        old = init.group("val") if init else None
        current = parse_literal(kind, old)
        if current is None:
            rep.files[path]["notes"].append(f"{key}: default {old} isn't a plain literal, set it by hand to {value!r}")
            continue
        if same(kind, current, value):
            rep.files[path]["same"] += 1
            continue
        new = cs_literal(kind, value, old)
        if init:
            line = line[:pos + init.start("val")] + new + line[pos + init.end("val"):]
        elif acc:
            line = line[:pos] + f" = {new};" + line[pos:]
        elif re.match(r"\s*;", line[pos:]):
            line = line[:pos] + f" = {new}" + line[pos:]
        else:
            rep.files[path]["notes"].append(f"{key}: not an auto-property, set its default by hand to {new}")
            continue
        doc.lines[i], doc.dirty = line, True
        rep.change(path, key, old if old is not None else "(none)", new)
        rep.files[path]["props"].append(key)


def gd_kind(gtype, old, value):
    if gtype:
        return GD_KINDS.get(gtype)
    if old is not None:
        old = old.strip()
        if color_bytes(old):
            return "color"
        if old in ("true", "false"):
            return "bool"
        if old.startswith('"'):
            return "string"
        if re.fullmatch(r"-?\d+", old):
            return "int"
        if re.fullmatch(r"-?[\d.]+(e-?\d+)?", old):
            return "float"
        return None
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, str):
        return "color" if parse_hex(value) else "string"
    return "float"


def gd_literal(kind, value, current):
    if kind == "color":
        rgba = parse_hex(value)
        if current and re.fullmatch(r"Color\s*\([^\"]*\)", current.strip()):
            return "Color(" + ", ".join(gfloat(b / 255) for b in rgba) + ")"
        return f'Color("{to_hex(rgba)}")'
    if kind == "bool":
        return "true" if value else "false"
    if kind == "string":
        return quote(value)
    if kind == "float":
        return repr(float(value))
    return num(value)


def apply_gd(doc, values, rep, path):
    for key, value in values.items():
        name = snake(key)
        decl = re.compile(rf"^(?P<anno>\s*(?:@\w+(?:\([^)]*\))?\s+)*)var\s+(?P<name>{re.escape(name)})\b\s*"
                          rf"(?::\s*(?P<type>\w+)\s*)?(?:(?P<op>:?=)\s*(?P<val>(?:{STRING}|[^#\"])*?))?\s*(?:#.*)?$")
        hit = None
        for i, line in enumerate(doc.lines):
            m = decl.match(line)
            if m and (re.search(GD_EXPORT, m.group("anno")) or (i and GD_EXPORT_LINE.fullmatch(doc.lines[i - 1]))):
                hit = i, m
                break
        if not hit:
            rep.files[path]["missing"].append(f"{key} ({name})")
            continue
        i, m = hit
        old, gtype = m.group("val"), m.group("type")
        kind = gd_kind(gtype, old, value)
        if not kind:
            rep.files[path]["notes"].append(f"{name}: {gtype or old} isn't handled, set it by hand to {value!r}")
            continue
        if not fits(kind, value):
            rep.files[path]["notes"].append(f"{name}: {value!r} doesn't fit {gtype or kind}")
            continue
        current = parse_literal(kind, old)
        if current is None:
            rep.files[path]["notes"].append(f"{name}: default {old} isn't a plain literal, set it by hand to {value!r}")
            continue
        if same(kind, current, value):
            rep.files[path]["same"] += 1
            continue
        new, line = gd_literal(kind, value, old), doc.lines[i]
        if old is not None:
            line = line[:m.start("val")] + new + line[m.end("val"):]
        else:
            pos = m.end("type") if gtype else m.end("name")
            line = line[:pos] + f" = {new}" + line[pos:]
        doc.lines[i], doc.dirty = line, True
        rep.change(path, name, old if old is not None else "(none)", new)
        rep.files[path]["props"].append(name)


# ---- shaders --------------------------------------------------------------------------------

def glsl_float(x):
    text = gfloat(x)
    return text if "." in text or "e" in text else text + ".0"


def shader_value(utype, text):
    """What a uniform's default stands for (colours as bytes), or None if it isn't a plain literal."""
    m = re.fullmatch(r"vec([34])\s*\(([^()]*)\)", text)
    if utype in ("vec3", "vec4") and m and utype.endswith(m.group(1)):
        try:
            ch = [float(c) for c in m.group(2).split(",")]
        except ValueError:
            return None
        ch = ch * int(m.group(1)) if len(ch) == 1 else ch
        return tuple(to_byte(c) for c in ch + [1.0] * (4 - len(ch))) if len(ch) == int(m.group(1)) else None
    if utype == "bool":
        return {"true": True, "false": False}.get(text)
    if utype in ("float", "int", "uint") and re.fullmatch(NUMBER + "[uUfF]?", text):
        return float(text.rstrip("uUfF"))
    return None


def shader_literal(utype, value):
    rgba = parse_hex(value)
    if rgba and utype in ("vec3", "vec4"):
        return f"{utype}(" + ", ".join(glsl_float(b / 255) for b in rgba[:int(utype[-1])]) + ")"
    if utype == "bool" and isinstance(value, bool):
        return "true" if value else "false"
    if utype == "float" and is_number(value):
        return repr(float(value))
    if utype in ("int", "uint") and is_number(value) and float(value).is_integer():
        return str(int(value)) + ("u" if utype == "uint" else "")
    return None


def apply_shader(doc, values, rep, path):
    uniforms = {}
    for i, line in enumerate(doc.lines):
        m = UNIFORM.match(line)
        if m:
            uniforms.setdefault(m.group("name"), (i, m))
    notes = rep.files[path]["notes"]
    for key, value in values.items():
        if key not in uniforms:
            rep.files[path]["missing"].append(key)
            continue
        i, m = uniforms[key]
        utype, old = m.group("type"), m.group("val")
        if old is None:
            notes.append(f"{key}: no default in the shader, set it by hand to {value!r}")
            continue
        new = shader_literal(utype, value)
        if new is None:
            if value == old:  # shown in the preview as the shader reads (a vec2, an expression): untouched
                rep.files[path]["same"] += 1
            else:
                notes.append(f"{key}: {value!r} doesn't fit {utype}, set it by hand")
            continue
        current, wanted = shader_value(utype, old), shader_value(utype, new)
        if current is None:
            notes.append(f"{key}: default {old} isn't a plain literal, set it by hand to {new}")
        elif current == wanted if isinstance(current, (tuple, bool)) else abs(current - wanted) < 1e-6:
            rep.files[path]["same"] += 1
        else:
            doc.lines[i], doc.dirty = doc.lines[i][:m.start("val")] + new + doc.lines[i][m.end("val"):], True
            rep.change(path, key, old, new)
            rep.files[path]["props"].append(f"shader_parameter/{key}")


def walk(root, suffixes):
    found = defaultdict(list)
    for dirpath, dirs, files in os.walk(root):
        top = Path(dirpath) == root
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (top and d in ("addons", "docs")))
        for f in files:
            if f.endswith(suffixes):
                found[f].append(Path(dirpath, f))
    return found


def scene_overrides(root, rep):
    """Scenes and resources that use a changed script or shader and set one of the changed properties: theirs wins."""
    changed = {p: r["props"] for p, r in rep.files.items() if r["props"]}
    if not changed:
        return []
    out = []
    for paths in walk(root, (".tscn", ".tres")).values():
        for scene in paths:
            text = scene.read_text(encoding="utf-8", errors="replace")
            for script, props in changed.items():
                if f'path="res://{script}"' not in text:
                    continue
                hits = [p for p in props if re.search(rf"^{re.escape(p)} = ", text, re.M)]
                if hits:
                    out.append(f"{Path(os.path.relpath(scene, root)).as_posix()} ({', '.join(hits)})")
    return out


def project_theme(root):
    p = root / "project.godot"
    m = re.search(r'^theme/custom="res://([^"]+)"', p.read_text(encoding="utf-8"), re.M) if p.is_file() else None
    return m.group(1) if m else None


# ---- main -----------------------------------------------------------------------------------

def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("feature", help="feature folder name under --mockups, or a path to a values.json")
    ap.add_argument("--mockups", default="docs/mockups")
    ap.add_argument("--theme", help="the Theme .tres (default: gui/theme/custom in project.godot)")
    ap.add_argument("--write", action="store_true", help="apply the changes (default: dry run)")
    args = ap.parse_args()

    root = Path.cwd()
    spec_path = Path(args.feature) if args.feature.endswith(".json") else Path(args.mockups, args.feature, "values.json")
    if not spec_path.is_file():
        sys.exit(f"no spec at {spec_path}")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    print(f"{spec_path.as_posix()}: feature {spec.get('feature')!r}, variant {spec.get('variant')!r}\n")
    theme = args.theme or project_theme(root)

    rep, docs, files = Report(), {}, None

    def open_doc(p):
        key = Path(os.path.relpath(p, root)).as_posix()
        if key not in docs:
            docs[key] = Doc(Path(p))
        return key, docs[key]

    def valid(group, name, values):
        bad = [k for k in values if not NAME.fullmatch(k)]
        if not NAME.fullmatch(name) or bad:
            rep.rejected += len(values)
            rep.notes.append(f"rejected {group!r}: {'its name' if not bad else 'keys ' + ', '.join(map(repr, bad))}"
                             " must be letters, digits, _ and /")
            return False
        return True

    for group, values in spec["values"].items():
        if not isinstance(values, dict):
            rep.notes.append(f"skipped {group!r}: not a group of values")
        elif group.startswith("theme:"):
            name = group.split(":", 1)[1].strip()
            if not valid(group, name, values):
                continue
            if not theme or not Path(theme).is_file():
                rep.notes.append(f"no theme ({theme or 'project.godot has no gui/theme/custom'}; pass --theme): skipped {group}")
                continue
            path, doc = open_doc(theme)
            apply_theme(doc, name, values, rep, path)
        elif group.lower().endswith("uniforms"):
            rep.notes.append(f"skipped {group!r} (shader uniforms, set from code at runtime): {', '.join(map(repr, values))}")
        elif valid(group, group[:-len(".gdshader")] if group.endswith(".gdshader") else group, values):
            files = files or walk(root, (".cs", ".gd", ".gdshader"))
            if group.endswith(".gdshader"):
                hits = files.get(group, [])
            else:
                hits = files.get(f"{group}.cs") or files.get(f"{snake(group)}.gd") or []
            if len(hits) != 1:
                where = ", ".join(Path(os.path.relpath(h, root)).as_posix() for h in hits)
                rep.no_script += len(values)
                rep.notes.append(f"{'several files for' if hits else 'no file for'} {group}"
                                 f"{': ' + where if hits else ''} (keys: {', '.join(values)})")
                continue
            path, doc = open_doc(hits[0])
            {".cs": apply_cs, ".gd": apply_gd, ".gdshader": apply_shader}[hits[0].suffix](doc, values, rep, path)

    rep.print(args.write, scene_overrides(root, rep))
    if args.write:
        for doc in docs.values():
            if doc.dirty:
                doc.save()


if __name__ == "__main__":
    main()
