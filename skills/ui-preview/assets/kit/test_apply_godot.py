"""Regression check for apply_godot.py's shader groups: runs it dry and with --write over a throwaway project.

    python test_apply_godot.py      # exit code = failed checks
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

APPLY = Path(__file__).with_name("apply_godot.py")
SHADER = """shader_type canvas_item;

// tube colours
uniform vec4 fill_color : source_color = vec4(0.2, 0.9, 0.3, 1.0); // the acid
uniform vec3 glass_tint: source_color = vec3(1.0, 0.5, 0.0);
uniform float wobble : hint_range(0.0, 2.0, 0.05) = 0.5;
uniform float speed = 1.5;
uniform int bubbles = 4;
uniform bool glow = true;
uniform vec2 offset = vec2(1.0, 2.0);
uniform float fill;
uniform vec4 splat : source_color = vec4(1.0);

void fragment() { COLOR = fill_color; }
"""
SPEC = {"variant": "a", "values": {
    "acid_gauge.gdshader": {"fill_color": "#ff0000ff", "glass_tint": "#00ff0080", "wobble": 1.25, "speed": 1.5,
                            "bubbles": 6, "glow": False, "offset": "vec2(1.0, 2.0)", "splat": "#ffffffff",
                            "fill": 0.3, "nope": 1},
    "dup.gdshader": {"x": 1},
    "none.gdshader": {"x": 1},
    "GaugeUniforms": {"level": 0.5},
}}
SCENE = """[gd_scene load_steps=3 format=3]

[ext_resource type="Shader" path="res://ui/hud/acid_gauge.gdshader" id="1"]

[sub_resource type="ShaderMaterial" id="m"]
shader = ExtResource("1")
shader_parameter/fill_color = Color(0, 1, 0, 1)
shader_parameter/speed = 2.0
"""


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    project = Path(tempfile.mkdtemp())
    failures = []

    def check(name, ok):
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
        if not ok:
            failures.append(name)

    def run(*extra):
        out = subprocess.run([sys.executable, str(APPLY), "values.json", *extra], cwd=project,
                             capture_output=True, text=True, encoding="utf-8")
        print(out.stdout + out.stderr)
        return out.stdout

    try:
        (project / "ui/hud").mkdir(parents=True)
        (project / "ui/a").mkdir()
        (project / "ui/b").mkdir()
        (project / "project.godot").write_text("config_version=5\n")
        (project / "ui/hud/acid_gauge.gdshader").write_bytes(SHADER.replace("\n", "\r\n").encode())
        (project / "ui/a/dup.gdshader").write_text("uniform float x = 0.0;\n")
        (project / "ui/b/dup.gdshader").write_text("uniform float x = 0.0;\n")
        (project / "ui/hud/gauge.tscn").write_text(SCENE)
        (project / "ui/other.tscn").write_text("[gd_scene format=3]\nshader_parameter/fill_color = Color(0, 1, 0, 1)\n")
        (project / "values.json").write_text(json.dumps(SPEC))

        out = run()
        for line in ["fill_color: vec4(0.2, 0.9, 0.3, 1.0) → vec4(1.0, 0.0, 0.0, 1.0)",
                     "glass_tint: vec3(1.0, 0.5, 0.0) → vec3(0.0, 1.0, 0.0)",
                     "wobble: 0.5 → 1.25", "bubbles: 4 → 6", "glow: true → false",
                     "fill: no default in the shader, set it by hand to 0.3", "not found: nope", "3 unchanged",
                     "several files for dup.gdshader: ui/a/dup.gdshader, ui/b/dup.gdshader", "no file for none.gdshader",
                     "skipped 'GaugeUniforms'", "scene overrides to check: ui/hud/gauge.tscn (shader_parameter/fill_color)",
                     "Dry run"]:
            check(f"dry run says {line!r}", line in out)
        check("dry run doesn't list a scene that doesn't use the shader", "other.tscn" not in out)
        check("dry run writes nothing", (project / "ui/hud/acid_gauge.gdshader").read_bytes() == SHADER.replace("\n", "\r\n").encode())

        check("--write says Written", "Written." in run("--write"))
        want = (SHADER.replace("vec4(0.2, 0.9, 0.3, 1.0)", "vec4(1.0, 0.0, 0.0, 1.0)")
                .replace("vec3(1.0, 0.5, 0.0)", "vec3(0.0, 1.0, 0.0)").replace("= 0.5;", "= 1.25;")
                .replace("= 4;", "= 6;").replace("= true;", "= false;"))
        got = (project / "ui/hud/acid_gauge.gdshader").read_bytes()
        check("--write rewrites only those defaults, keeping CRLF and comments", got == want.replace("\n", "\r\n").encode())
        check("second run has nothing to change", "0 changes" in run())
    finally:
        shutil.rmtree(project, ignore_errors=True)
    print(f"{len(failures)} failed" if failures else "all passed")
    sys.exit(len(failures))


if __name__ == "__main__":
    main()
