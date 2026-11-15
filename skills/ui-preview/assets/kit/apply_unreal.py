#!/usr/bin/env python3
"""Write a ui-preview spec (<mockups>/<feature>/values.json) into an Unreal project's C++ class defaults.

Usage, from the project root:
    python docs/mockups/kit/apply_unreal.py <feature | path/to/values.json>
        [--mockups docs/mockups] [--target ini | header] [--write]

Dry run by default: prints each change as `old -> new`, the keys that have no UPROPERTY yet (with a declaration
to paste), and a summary. --write applies the changes.

Each group of values.json is a C++ class, named without its U / A / F prefix (the name its config section and Python
use): "HudSettings" is UHudSettings, found by its declaration in any .h under Source/ or Plugins/*/Source/. Each key
is one of its UPROPERTYs (EditAnywhere / EditDefaultsOnly / Config); a struct's member is "Prop/X" (FVector2D,
FVector, FIntPoint: X Y Z; FMargin: Left Top Right Bottom). Groups that name no class are listed, not guessed.

Targets:
  ini     (default) for a Config class (UCLASS(Config = Game) and the like, such as a UDeveloperSettings): each changed
          value becomes `Key=Value` in [/Script/<Module>.<Class>] of Config/Default<Config>.ini, the way the editor's
          Project Settings save it. The section is created when missing (module = the folder under Source/). A class
          without Config is listed for --target header.
  header  the default in the declaration itself (`float Width = 520.f;`, `FVector2D At{1.f, 2.f};`), for any class.
          A key an ini already overrides is flagged: the ini wins over the header. Blueprint subclasses can override
          class defaults too; this can't see inside .uasset files, so check them in the editor.

Values are numbers, booleans, enum names or colours "#rrggbbaa" (sRGB). FLinearColor is linear light: the colour goes
through the inverse sRGB curve on the way in and compares at 8-bit sRGB precision. A default that isn't a plain
literal (an expression, a constant from elsewhere) is listed to do by hand, never overwritten. Group and key names
must be identifiers (letters, digits, _ and one / for a struct member); anything else is rejected unread.
"""
import argparse
import json
import math
import os
import re
import sys
from pathlib import Path

NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(/[A-Za-z_][A-Za-z0-9_]*)?")
MEMBERS = {"FVector2D": ("X", "Y"), "FVector2f": ("X", "Y"), "FIntPoint": ("X", "Y"), "FVector": ("X", "Y", "Z"),
           "FVector3f": ("X", "Y", "Z"), "FIntVector": ("X", "Y", "Z"), "FMargin": ("Left", "Top", "Right", "Bottom")}
INT_MEMBERS = ("FIntPoint", "FIntVector")
FLOATS = ("float", "double")
INTS = ("int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64", "int")
NAMED = {"White": (255, 255, 255, 255), "Black": (0, 0, 0, 255), "Transparent": (0, 0, 0, 0), "Red": (255, 0, 0, 255),
         "Green": (0, 255, 0, 255), "Blue": (0, 0, 255, 255), "Yellow": (255, 255, 0, 255)}
DECL = re.compile(r"\s*((?:\w+::)*\w+(?:\s*<[^;=]*?>)?)\s+(\w+)\s*(=\s*([^;]+?)|(\{[^;]*\}))?\s*;")
EDITABLE = re.compile(r"\b(EditAnywhere|EditDefaultsOnly|Config|GlobalConfig)\b")


def read(path):
    """A text file as it is on disk (line endings kept, so a write changes only what it means to)."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        return f.read()


# ---- colours ----

def to_srgb(c):
    c = min(1.0, max(0.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex8(rgba):
    return "#" + "".join(f"{max(0, min(255, round(x))):02x}" for x in rgba)


def parse_hex(s):
    m = re.fullmatch(r"#([0-9a-fA-F]{6})([0-9a-fA-F]{2})?", s)
    if not m:
        return None
    h = m.group(1) + (m.group(2) or "ff")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4, 6))


# ---- C++ header ----

def strip_comments(text):
    """Blank out comments and string contents' line breaks, keeping offsets, so brackets can be matched."""
    out, i, n = list(text), 0, len(text)
    while i < n:
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out[i:j] = " " * (j - i)
            i = j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out[i:j] = [c if c == "\n" else " " for c in text[i:j]]
            i = j
        elif text[i] == '"':
            j = i + 1
            while j < n and text[j] != '"' and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            i = j + 1
        else:
            i += 1
    return "".join(out)


def close(code, i, open_c="(", close_c=")"):
    """Index just past the bracket matching code[i]."""
    depth = 0
    for j in range(i, len(code)):
        if code[j] == open_c:
            depth += 1
        elif code[j] == close_c:
            depth -= 1
            if depth == 0:
                return j + 1
    return len(code)


def specifiers(s):
    """UPROPERTY / UCLASS specifier text -> {name: value or True}, meta = (...) flattened in."""
    out = {}
    for m in re.finditer(r'(\w+)\s*=\s*("([^"]*)"|\(([^()]*)\)|[\w.\-]+)|(\w+)', s):
        if m.group(5):
            out[m.group(5)] = True
        elif m.group(4) is not None:
            out.update(specifiers(m.group(4)))
        else:
            out[m.group(1)] = m.group(3) if m.group(3) is not None else m.group(2)
    return out


def number(s):
    s = s.strip()
    m = re.fullmatch(r"([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)[fF]?", s)
    if m:
        v = float(m.group(1))
        return int(v) if re.fullmatch(r"[-+]?\d+", m.group(1)) else v
    m = re.fullmatch(r"0[xX]([0-9a-fA-F]+)[uU]?", s)
    return int(m.group(1), 16) if m else None


def args_of(expr, ctor):
    """'FVector2D(1.f, 2.f)', '{1.f, 2.f}' or '(1.f, 2.f)' -> ['1.f', '2.f'] (top-level commas)."""
    expr = expr.strip()
    if expr.startswith(ctor):
        expr = expr[len(ctor):].strip()
    if not expr or expr[0] not in "({" or expr[-1] not in ")}":
        return None
    inner, parts, depth, cur = expr[1:-1], [], 0, ""
    for c in inner:
        if c in "({":
            depth += 1
        elif c in ")}":
            depth -= 1
        if c == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += c
    if cur.strip():
        parts.append(cur.strip())
    return parts


def colour_default(ctype, expr):
    """A colour default -> (r, g, b, a) sRGB bytes, or None when it isn't a literal."""
    expr = expr.strip()
    m = re.fullmatch(r"F(?:Linear)?Color::(\w+)", expr)
    if m:
        return NAMED.get(m.group(1))
    inner = args_of(expr, "FLinearColor") if ctype == "FLinearColor" else None
    if inner is not None and len(inner) == 1 and inner[0].startswith("FColor"):
        expr = inner[0]   # FLinearColor(FColor(...)): sRGB bytes
        inner = None
    if inner is not None:
        v = [number(x) for x in inner]
        if len(v) in (3, 4) and None not in v:
            r, g, b = (to_srgb(x) * 255 for x in v[:3])
            return (r, g, b, (v[3] if len(v) == 4 else 1.0) * 255)
        return None
    inner = args_of(expr, "FColor")
    v = [number(x) for x in inner] if inner is not None else [None]
    if len(v) in (3, 4) and None not in v:
        return tuple(v[:3]) + ((v[3] if len(v) == 4 else 255),)
    return None


def value_of(ctype, expr, enums):
    """The default expression -> a values.json-shaped value (dict for structs), or None when not a literal."""
    if expr is None:   # UObjects are zero-initialised
        return {m: 0 for m in MEMBERS[ctype]} if ctype in MEMBERS else False if ctype == "bool" else 0 if (ctype in FLOATS or ctype in INTS) else None
    e = expr.strip()
    if ctype == "bool":
        return {"true": True, "false": False}.get(e)
    if ctype in FLOATS or ctype in INTS:
        return number(e)
    if ctype in ("FLinearColor", "FColor"):
        c = colour_default(ctype, e)
        return hex8(c) if c else None
    if ctype in MEMBERS:
        if re.fullmatch(r"\w+::Zero(Vector)?", e):
            return {m: 0 for m in MEMBERS[ctype]}
        parts = args_of(e, ctype)
        nums = [number(p) for p in parts] if parts else [None]
        if None in nums:
            return None
        if len(nums) == 1:
            nums *= len(MEMBERS[ctype])
        if ctype == "FMargin" and len(nums) == 2:   # FMargin(horizontal, vertical)
            nums = [nums[0], nums[1], nums[0], nums[1]]
        return dict(zip(MEMBERS[ctype], nums)) if len(nums) == len(MEMBERS[ctype]) else None
    if ctype in enums:
        m = re.fullmatch(rf"{re.escape(ctype)}::(\w+)", e)
        return m.group(1) if m and m.group(1) in enums[ctype] else None
    return None


def comment_above(text, at):
    """The /** */ block or // lines right above offset `at` (blank lines break it), on one line."""
    above = text[:at].rstrip()
    if above.endswith("*/"):
        start = above.rfind("/*")
        body = above[start + 2:-2] if start >= 0 else ""
    else:
        lines = []
        for line in reversed(above.split("\n")):
            if not line.strip().startswith("//"):
                break
            lines.append(line.strip()[2:])
        body = "\n".join(reversed(lines))
    return re.sub(r"\s+", " ", re.sub(r"^\s*\*+", "", body, flags=re.M)).strip(" *")


def parse_header(path):
    """-> {class name without prefix: {"prefix", "config", "module", "path", "props": {name: prop}}}"""
    text = read(path)
    code = strip_comments(text)
    enums = {}
    for m in re.finditer(r"\benum\s+(?:class\s+)?(\w+)\s*(?::\s*\w+\s*)?\{", code):
        body = code[m.end():close(code, m.end() - 1, "{", "}") - 1]
        body = re.sub(r"\w+\s*\([^()]*\)", "", body)   # UMETA(...)
        enums[m.group(1)] = [re.split(r"[\s=]", x.strip())[0] for x in body.split(",") if x.strip()]
    parts = Path(path).resolve().parts
    module = parts[len(parts) - 1 - parts[::-1].index("Source") + 1] if "Source" in parts else None
    classes = {}
    for m in re.finditer(r"\bUCLASS\s*\(", code):
        spec = specifiers(code[m.end():close(code, m.end() - 1) - 1])
        d = re.compile(r"\s*(?:class|struct)\s+(?:\w+_API\s+)?([UAF])(\w+)\b[^{;]*\{").match(code, close(code, m.end() - 1))
        if not d:
            continue
        body_end = close(code, d.end() - 1, "{", "}")
        cls = {"prefix": d.group(1), "config": spec.get("Config") or spec.get("config"), "module": module,
               "path": str(path), "props": {}}
        for p in re.finditer(r"\bUPROPERTY\s*\(", code[d.end():body_end]):
            at = d.end() + p.start()
            spec_end = close(code, d.end() + p.end() - 1)
            pspec = specifiers(code[d.end() + p.end():spec_end - 1])
            decl = DECL.match(code, spec_end)
            if not decl or not EDITABLE.search(code[d.end() + p.end():spec_end - 1]):
                continue
            ctype, name = decl.group(1), decl.group(2)
            expr = decl.group(4) or decl.group(5)
            span = (decl.start(4), decl.end(4)) if decl.group(4) else (decl.start(5), decl.end(5)) if decl.group(5) else None
            hint = comment_above(text, at)
            cls["props"][name] = {"type": ctype, "expr": expr, "span": span, "value": value_of(ctype, expr, enums),
                                  "category": pspec.get("Category", ""), "config": bool(re.search(r"\b(Global)?Config\b", code[d.end() + p.end():spec_end - 1])),
                                  "min": number(str(pspec.get("ClampMin", pspec.get("UIMin", "x")))),
                                  "max": number(str(pspec.get("ClampMax", pspec.get("UIMax", "x")))),
                                  "options": enums.get(ctype), "hint": hint[:300]}
        classes[d.group(2)] = cls
    return classes


def find_class(root, group):
    """The header declaring U/A/F<group> (or <group> itself when it carries the prefix)."""
    names = {group} | ({group[1:]} if group[:1] in "UAF" and group[1:2].isupper() else set())
    pat = re.compile(r"\b(?:class|struct)\s+(?:\w+_API\s+)?[UAF](%s)\b" % "|".join(map(re.escape, names)))
    hits = []
    for base in [root / "Source"] + sorted((root / "Plugins").glob("**/Source")):
        for h in sorted(base.rglob("*.h")) if base.is_dir() else []:
            try:
                text = h.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            m = pat.search(text)
            if m and "UCLASS" in text:
                hits.append((h, m.group(1)))
    return hits


# ---- ini ----

def ini_sections(text):
    """-> {section header: (start offset of its body, end offset)}"""
    out, heads = {}, list(re.finditer(r"^\[([^\]\r\n]+)\][ \t]*\r?$", text, re.M))
    for i, m in enumerate(heads):
        out[m.group(1)] = (m.end() + 1 if m.end() < len(text) else m.end(), heads[i + 1].start() if i + 1 < len(heads) else len(text))
    return out


def ini_section_for(text, cls_name):
    for head in ini_sections(text):
        if re.fullmatch(rf"/Script/\w+\.{re.escape(cls_name)}", head):
            return head
    return None


def ini_value(raw, prop):
    """An ini value string -> values.json-shaped value."""
    t, raw = prop["type"], raw.strip()
    if t == "bool":
        return raw.lower() == "true"
    if t in FLOATS or t in INTS:
        return number(raw)
    if t in MEMBERS or t in ("FLinearColor", "FColor"):
        fields = dict(re.findall(r"(\w+)=([-+\d.eE]+)", raw))
        if t in MEMBERS:
            return {m: number(fields.get(m, "0")) for m in MEMBERS[t]}
        c = [float(fields.get(k, "1" if k == "A" else "0")) for k in "RGBA"]
        if t == "FLinearColor":
            return hex8([to_srgb(x) * 255 for x in c[:3]] + [c[3] * 255])
        return hex8(c[:3] + [c[3] if "A" in fields else 255])
    return raw.strip('"')


def ini_text(value, prop):
    t = prop["type"]
    if t == "bool":
        return "True" if value else "False"
    if t in INTS:
        return str(int(value))
    if t in FLOATS:
        return f"{float(value):.6f}"
    if t in MEMBERS:
        fmt = (lambda x: str(int(x))) if t in INT_MEMBERS else (lambda x: f"{float(x):.6f}")
        return "(" + ",".join(f"{m}={fmt(value[m])}" for m in MEMBERS[t]) + ")"
    if t == "FLinearColor":
        r, g, b, a = parse_hex(value)
        return "(R={:.6f},G={:.6f},B={:.6f},A={:.6f})".format(*[to_linear(x / 255) for x in (r, g, b)], a / 255)
    if t == "FColor":
        r, g, b, a = parse_hex(value)
        return f"(B={b},G={g},R={r},A={a})"
    return str(value)


def set_ini(text, head, key, line_value, nl):
    """Set `key=value` inside [head] (replacing the last plain assignment), creating the section if needed."""
    secs = ini_sections(text)
    if head not in secs:
        sep = "" if not text or text.endswith(("\n", "\r")) else nl
        return f"{text}{sep}{nl if text.strip() else ''}[{head}]{nl}{key}={line_value}{nl}"
    start, end = secs[head]
    body = text[start:end]
    hits = list(re.finditer(rf"^{re.escape(key)}=.*?(?=\r?$)", body, re.M))
    if hits:
        h = hits[-1]
        return text[:start + h.start()] + f"{key}={line_value}" + text[start + h.end():]
    insert = start + len(body.rstrip("\r\n \t"))
    if insert > start and not text[:insert].endswith(("\n", "\r")):
        return text[:insert] + f"{nl}{key}={line_value}" + text[insert:]
    return text[:insert] + f"{key}={line_value}{nl}" + text[insert:]


# ---- C++ literals ----

def cpp_float(x):
    s = f"{float(x):.6g}"
    return (s if any(c in s for c in ".e") else s + ".") + "f"


def cpp_text(value, prop):
    t, old = prop["type"], (prop["expr"] or "").strip()
    brace = old.startswith("{")
    if t == "bool":
        return "true" if value else "false"
    if t in INTS:
        return str(int(value))
    if t == "float":
        return cpp_float(value)
    if t == "double":
        return f"{float(value):.10g}"
    if t in MEMBERS:
        fmt = (lambda x: str(int(x))) if t in INT_MEMBERS else cpp_float
        inner = ", ".join(fmt(value[m]) for m in MEMBERS[t])
        return f"{{{inner}}}" if brace else f"{t}({inner})"
    if t in ("FLinearColor", "FColor"):
        r, g, b, a = parse_hex(value)
        if t == "FColor" or "FColor" in old:   # keep the author's sRGB bytes form
            fcolor = f"FColor(0x{r:02X}, 0x{g:02X}, 0x{b:02X}" + (f", 0x{a:02X})" if a != 255 else ")")
            return fcolor if t == "FColor" else f"FLinearColor({fcolor})"
        lin = [to_linear(x / 255) for x in (r, g, b)] + [a / 255]
        return f"FLinearColor({', '.join(cpp_float(round(x, 4)) for x in lin)})"
    if prop.get("options"):
        return f"{t}::{value}"
    return None


# ---- main ----

def same(prop, a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return all(same(prop, a.get(k), b.get(k)) for k in set(a) | set(b))
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6)
    if isinstance(a, str) and isinstance(b, str) and a.startswith("#") and b.startswith("#"):
        return parse_hex(a) == parse_hex(b)
    return a == b


def declaration(key, value):
    if isinstance(value, bool):
        t, v = "bool", "true" if value else "false"
    elif isinstance(value, (int, float)):
        t, v = "float", cpp_float(value)
    elif isinstance(value, str) and parse_hex(value):
        r, g, b, a = parse_hex(value)
        t, v = "FLinearColor", f"FLinearColor(FColor(0x{r:02X}, 0x{g:02X}, 0x{b:02X}, 0x{a:02X}))"
    else:
        t, v = "FString", json.dumps(str(value))
    return f'UPROPERTY(Config, EditAnywhere, Category = "...") {t} {key} = {v};'


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("feature")
    ap.add_argument("--mockups", default="docs/mockups")
    ap.add_argument("--target", choices=("ini", "header"), default="ini")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    root = Path.cwd()
    spec_path = Path(a.feature) if a.feature.endswith(".json") else root / a.mockups / a.feature / "values.json"
    if not spec_path.is_file():
        sys.exit(f"no spec at {spec_path} (press Save in the preview first)")
    values = json.loads(spec_path.read_text(encoding="utf-8")).get("values", {})

    edits = {}       # file -> new text
    changes, todo, missing = [], [], []
    for group, keys in values.items():
        if not re.fullmatch(r"[A-Za-z_]\w*", group) or not all(NAME.fullmatch(k) for k in keys):
            todo.append(f"{group}: rejected (group and key names must be identifiers)")
            continue
        hits = find_class(root, group)
        if len(hits) != 1:
            todo.append(f"{group}: {'no' if not hits else 'several'} C++ classes named U/A/F{group}"
                        + (": " + ", ".join(str(h.relative_to(root)) for h, _ in hits) if hits else ""))
            continue
        header, cname = hits[0]
        cls = parse_header(header)[cname]
        header_rel = header.relative_to(root).as_posix()
        # Recombine struct members ("At/X", "At/Y") into one value per property.
        wanted = {}
        for key, v in keys.items():
            prop_name, _, member = key.partition("/")
            prop = cls["props"].get(prop_name)
            if prop is None:
                missing.append(f"{group}.{key}: no UPROPERTY yet in {header_rel}: {declaration(key, v)}")
                continue
            if member:
                if prop["type"] not in MEMBERS or member not in MEMBERS[prop["type"]]:
                    todo.append(f"{group}.{key}: {prop['type']} {prop_name} has no member {member}")
                    continue
                wanted.setdefault(prop_name, {})[member] = v
            else:
                wanted[prop_name] = v

        ini_path = root / "Config" / f"Default{cls['config']}.ini" if cls["config"] else None
        ini = read(ini_path) if ini_path and ini_path.is_file() else ""
        head = ini_section_for(ini, cname) if ini else None
        overrides = {}
        if head:
            s, e = ini_sections(ini)[head]
            for m in re.finditer(r"^(\w+)=(.*?)\r?$", ini[s:e], re.M):
                overrides[m.group(1)] = m.group(2)

        for prop_name, v in wanted.items():
            prop = cls["props"][prop_name]
            default = prop["value"]
            current = ini_value(overrides[prop_name], prop) if prop_name in overrides else default
            if isinstance(v, dict):
                if not isinstance(current, dict):
                    todo.append(f"{group}.{prop_name}: default `{prop['expr']}` isn't a literal; set it by hand")
                    continue
                v = {**(current if a.target == "ini" else default), **v}
            if prop["type"] in ("FLinearColor", "FColor") and not (isinstance(v, str) and parse_hex(v)):
                todo.append(f"{group}.{prop_name}: {v!r} isn't a colour")
                continue
            if a.target == "ini":
                if not (cls["config"] and prop["config"]):
                    todo.append(f"{group}.{prop_name}: not a Config property; use --target header")
                    continue
                if current is not None and same(prop, current, v):
                    continue
                where = f"{ini_path.relative_to(root).as_posix()} [/Script/{cls['module']}.{cname}]" if not head else f"{ini_path.relative_to(root).as_posix()} [{head}]"
                changes.append(f"{group}.{prop_name}: {fmt(current)} -> {fmt(v)}  ({where})")
                if not cls["module"] and not head:
                    todo.append(f"{group}: no module folder under Source/ for a new section; add [/Script/<Module>.{cname}] by hand")
                    continue
                nl = "\r\n" if "\r\n" in ini else "\n"
                ini = set_ini(ini, head or f"/Script/{cls['module']}.{cname}", prop_name, ini_text(v, prop), nl)
                head = head or f"/Script/{cls['module']}.{cname}"
                edits[ini_path] = ini
            else:
                if prop_name in overrides:
                    todo.append(f"{group}.{prop_name}: {ini_path.relative_to(root).as_posix()} overrides it ({overrides[prop_name]}); the ini wins over the header")
                if default is None:
                    todo.append(f"{group}.{prop_name}: default `{prop['expr']}` isn't a literal; set it by hand")
                    continue
                if same(prop, default, v):
                    continue
                lit = cpp_text(v, prop)
                if lit is None:
                    todo.append(f"{group}.{prop_name}: can't write a {prop['type']} default; set it by hand")
                    continue
                text = edits.get(header) or read(header)
                fresh = default_span(text, cname, prop_name)
                if fresh is None:
                    todo.append(f"{group}.{prop_name}: no default to replace in {header_rel}; add ` = {lit}` by hand")
                    continue
                s, e, eq = fresh
                text = text[:s] + (lit if eq else (" = " + lit)) + text[e:]
                edits[header] = text
                changes.append(f"{group}.{prop_name}: {fmt(default)} -> {fmt(v)}  ({header_rel}: {lit})")

    for line in changes:
        print("change ", line)
    for line in missing:
        print("missing", line)
    for line in todo:
        print("by hand", line)
    print(f"\n{len(changes)} change(s), {len(missing)} missing UPROPERTY(s), {len(todo)} to do by hand"
          + ("" if a.write else ". Dry run: --write applies."))
    if a.write:
        for path, text in edits.items():
            tmp = Path(str(path) + ".tmp")
            tmp.write_text(text, encoding="utf-8", newline="")
            os.replace(tmp, path)
            print("wrote", path.relative_to(root).as_posix())
        if edits:
            print("Restart the editor (or reload the config) to see ini changes; rebuild for header changes.")


def default_span(text, cname, prop_name):
    """Where a property's default sits in (possibly already edited) header text: (start, end, has a default)."""
    code = strip_comments(text)
    m = re.search(rf"\b(?:class|struct)\s+(?:\w+_API\s+)?[UAF]{re.escape(cname)}\b[^{{;]*\{{", code)
    if not m:
        return None
    for p in re.compile(r"\bUPROPERTY\s*\(").finditer(code, m.end(), close(code, m.end() - 1, "{", "}")):
        decl = DECL.match(code, close(code, p.end() - 1))
        if decl and decl.group(2) == prop_name:
            if decl.group(4):
                return decl.start(4), decl.end(4), True
            if decl.group(5):
                return decl.start(5), decl.end(5), True
            return decl.end(2), decl.end(2), False
    return None


def fmt(v):
    if isinstance(v, dict):
        return "(" + ", ".join(f"{k}={fmt(x)}" for k, x in v.items()) + ")"
    if isinstance(v, float):
        return f"{v:g}"
    return "unset" if v is None else str(v)


if __name__ == "__main__":
    main()
