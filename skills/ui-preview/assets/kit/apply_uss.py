"""Writes a preview's approved values.json back into the project's UI Toolkit .uss files.

    python docs/mockups/kit/apply_uss.py hud                  # from the project root: dry run, prints old -> new
    python docs/mockups/kit/apply_uss.py hud --write          # apply
    python docs/mockups/kit/apply_uss.py path/to/values.json  # a values.json anywhere
    python docs/mockups/kit/apply_uss.py hud --mockups design/previews

Each group named "uss: <stem>" (what unity_theme.js's UnityTheme.groups() makes) goes to the one <stem>.uss under the
project. Folders that never hold your .uss are not searched, at any depth: Library, Temp, Logs, obj, UserSettings,
Build*, docs and hidden folders (.git, ...). Each key is a custom property (--name): the first declaration of it gets
the new value; colours as #rrggbb (#rrggbbaa below full alpha), numbers keep the original's unit (px, %, s, ms, deg...).
Values equal to what the file already says are left alone, so formatting like #fff survives. Group and key names that
aren't plain identifiers are refused. Files are written atomically (temp file, then swap) with their line endings
kept. Stdlib only.
"""
import argparse
import fnmatch
import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path

PRUNE = {"Library", "Temp", "Logs", "obj", "UserSettings", "docs"}
KEY = re.compile(r"--?[A-Za-z_][A-Za-z0-9_-]*")
STEM = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_. -]*")
DECL = re.compile(r"[{;]\s*(--[\w-]+)\s*:\s*([^;}]+)")
NUMBER = re.compile(r"(-?\d*\.?\d+)([A-Za-z%]*)")


def css_color(s):
    """'#rgb', '#rrggbb(aa)', 'rgb()/rgba()' (commas or spaces, channels 0-255 or %, alpha 0-1 or %) -> '#rrggbbaa'."""
    s = s.strip()
    m = re.fullmatch(r"#([0-9a-fA-F]{3,8})", s)
    if m:
        h = m.group(1)
        if len(h) <= 4:
            h = "".join(c * 2 for c in h)
        if len(h) == 6:
            h += "ff"
        return "#" + h.lower() if len(h) == 8 else None
    m = re.fullmatch(r"rgba?\(([^)]*)\)", s, re.I)
    if not m:
        return None
    parts = [x for x in re.split(r"[\s,/]+", m.group(1).strip()) if x]
    if len(parts) not in (3, 4):
        return None
    try:
        rgb = [float(x[:-1]) / 100 if x.endswith("%") else float(x) / 255 for x in parts[:3]]
        alpha = [float(x[:-1]) / 100 if x.endswith("%") else float(x) for x in parts[3:]] or [1.0]
    except ValueError:
        return None
    return "#" + "".join(f"{round(min(1, max(0, x)) * 255):02x}" for x in rgb + alpha)


def number(v):
    return str(int(v)) if float(v).is_integer() else repr(float(v))


def formatted(new, old):
    """The text to write for `new` over the declaration `old`, or None to leave it as it is."""
    if isinstance(new, str) and css_color(new):
        if css_color(new) == css_color(old):
            return None
        h = css_color(new)
        return h[:7] if h.endswith("ff") else h
    if isinstance(new, (int, float)) and not isinstance(new, bool) and math.isfinite(new):
        m = NUMBER.fullmatch(old.strip())
        if m and float(m.group(1)) == float(new):
            return None
        return number(new) + (m.group(2) if m else "")
    return None  # strings and aliases aren't tunable in the panel


def find_uss(root, stem):
    name = stem + ".uss"
    hits = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in PRUNE and not d.startswith(".") and not fnmatch.fnmatchcase(d, "Build*")]
        if name in files:
            hits.append(Path(folder) / name)
    return hits


def write_atomic(path, text):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def apply(path, values, write):
    with path.open(encoding="utf-8", newline="") as f:
        text = f.read()
    # Comments blanked out (same length) so offsets stay valid and nothing inside a comment matches.
    masked = re.sub(r"/\*.*?\*/", lambda m: " " * len(m.group()), text, flags=re.S)
    spans = {}
    for m in DECL.finditer(masked):
        spans.setdefault(m.group(1), (m.start(2), m.start(2) + len(m.group(2).rstrip())))
    edits, unmatched = [], []
    for key, new in values.items():
        if key not in spans:
            unmatched.append(key)
            continue
        start, end = spans[key]
        out = formatted(new, text[start:end])
        if out is not None:
            edits.append((start, end, key, text[start:end], out))
    print(path)
    for _, _, key, old, out in edits:
        print(f"  {key}: {old} -> {out}")
    if not edits:
        print("  no changes")
    for key in unmatched:
        print(f"  unmatched: {key} (no declaration in this file)")
    if write and edits:
        for start, end, _, _, out in sorted(edits, reverse=True):
            text = text[:start] + out + text[end:]
        write_atomic(path, text)
    return len(edits)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("target", help="a feature name (its <mockups>/<feature>/values.json) or a values.json path")
    parser.add_argument("--mockups", default="docs/mockups", help="the previews folder, from the project root")
    parser.add_argument("--write", action="store_true", help="apply the changes (default: dry run)")
    args = parser.parse_args()

    root = Path.cwd()
    source = Path(args.target)
    if source.suffix != ".json":
        source = root / args.mockups / args.target / "values.json"
    groups = json.loads(source.read_text(encoding="utf-8"))["values"]

    changed = 0
    for group, values in groups.items():
        if not group.startswith("uss: "):
            continue
        stem = group[len("uss: "):]
        bad = [repr(k) for k in values if not KEY.fullmatch(k)]
        if not STEM.fullmatch(stem) or bad:
            print(f"{group!r}: refused, not a plain file stem / property name: {', '.join(bad) or repr(stem)}", file=sys.stderr)
            continue
        hits = find_uss(root, stem)
        if len(hits) != 1:
            print(f"{group}: skipped, {len(hits)} files named {stem}.uss under the project", *hits, sep="\n  ", file=sys.stderr)
            continue
        changed += apply(hits[0], values, args.write)
    print(f"{changed} change(s) {'written' if args.write else 'to write; run with --write to apply'}")


if __name__ == "__main__":
    main()
