"""Regression check for apply_unreal.py: runs it dry, then with --write to the ini and to the header, over a throwaway
Unreal project, and checks a second run finds nothing left to change.

    python test_apply_unreal.py      # exit code = failed checks
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

APPLY = Path(__file__).resolve().with_name("apply_unreal.py")
HEADER = """#pragma once
#include "Engine/DeveloperSettings.h"
#include "HudSettings.generated.h"

UENUM(BlueprintType)
enum class EHudEase : uint8
{
	Linear,
	OutCubic UMETA(DisplayName = "Out cubic"),
	OutBack = 5
};

/** The HUD's look (Project Settings > Game > Hud). */
UCLASS(Config = Game, DefaultConfig, meta = (DisplayName = "Hud"))
class HUDEXAMPLE_API UHudSettings : public UDeveloperSettings
{
	GENERATED_BODY()
public:
	/** The panel's width (px). */
	UPROPERTY(Config, EditAnywhere, Category = "Panel", meta = (ClampMin = "100", ClampMax = "1200"))
	float PanelWidth = 520.f;

	// Rows in the list.
	UPROPERTY(Config, EditAnywhere, Category = "Panel")
	int32 Rows = 4;

	UPROPERTY(Config, EditAnywhere, Category = "Panel")
	bool bShowIcons = true;

	UPROPERTY(Config, EditAnywhere, Category = "Panel|Colour")
	FLinearColor Accent = FLinearColor(FColor(0xFF, 0xC3, 0x0F));

	UPROPERTY(Config, EditAnywhere, Category = "Panel|Colour")
	FLinearColor Fill = FLinearColor(0.05f, 0.05f, 0.05f, 0.9f);

	UPROPERTY(Config, EditAnywhere, Category = "Panel")
	FVector2D Offset{48.f, 32.f};

	UPROPERTY(Config, EditAnywhere, Category = "Motion")
	EHudEase Ease = EHudEase::OutCubic;

	UPROPERTY(Config, EditAnywhere, Category = "Motion")
	float FadeSeconds = 0.25f;   // overridden in DefaultGame.ini

	UPROPERTY(Config, EditAnywhere, Category = "Motion")
	float Delay;

	UPROPERTY(Config, EditAnywhere, Category = "Art")
	TSoftObjectPtr<UTexture2D> Frame;

	UPROPERTY(VisibleAnywhere, Category = "Debug")
	float Hidden = 1.f;
};

UCLASS()
class HUDEXAMPLE_API UHudBar : public UUserWidget
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Bar")
	float Segments = 10.f;
};
"""
INI = "[/Script/Engine.Engine]\r\nGameEngine=x\r\n\r\n[/Script/HudExample.HudSettings]\r\nFadeSeconds=0.400000\r\n\r\n[Other]\r\nA=1\r\n"
SPEC = {"variant": "a", "values": {
    "HudSettings": {"PanelWidth": 640, "Rows": 4, "bShowIcons": False, "Accent": "#ff0000ff", "Fill": "#0d0d0de6",
                    "Offset/X": 64, "Offset/Y": 32, "Ease": "OutBack", "FadeSeconds": 0.4, "Delay": 0.1,
                    "NewThing": 0.5, "Hidden": 2},
    "HudBar": {"Segments": 12},
    "bad name": {"x": 1},
    "Ghost": {"x": 1},
}}


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
        (project / "Source/HudExample/UI").mkdir(parents=True)
        header = project / "Source/HudExample/UI/HudSettings.h"
        header.write_text(HEADER, encoding="utf-8", newline="\n")
        (project / "Config").mkdir()
        ini = project / "Config/DefaultGame.ini"
        ini.write_bytes(INI.encode())
        (project / "values.json").write_text(json.dumps(SPEC), encoding="utf-8")

        out = run()
        check("dry run changes nothing", header.read_text(encoding="utf-8") == HEADER and ini.read_bytes() == INI.encode())
        check("float", "PanelWidth: 520 -> 640" in out)
        check("unchanged int not listed", "Rows:" not in out)
        check("bool", "bShowIcons: True -> False" in out)
        check("FColor-form FLinearColor", "Accent: #ffc30fff -> #ff0000ff" in out)
        check("linear FLinearColor read through sRGB", "Fill: #" in out and "-> #0d0d0de6" in out)
        check("struct members recombined", "Offset: (X=48, Y=32) -> (X=64, Y=32)" in out)
        check("enum", "Ease: OutCubic -> OutBack" in out)
        check("ini override is the current value", "FadeSeconds" not in out)
        check("no default reads as 0", "Delay: 0 -> 0.1" in out)
        check("missing UPROPERTY with a declaration", "NewThing: no UPROPERTY yet" in out and "float NewThing = 0.5f;" in out)
        check("VisibleAnywhere isn't tunable", "Hidden: no UPROPERTY yet" in out)
        check("non-Config class sent to --target header", "HudBar.Segments: not a Config property" in out)
        check("bad group rejected", "bad name: rejected" in out)
        check("unknown class listed", "Ghost: no C++ classes" in out)

        run("--write")
        text = ini.read_bytes().decode()
        check("ini keeps CRLF", "\r\n" in text and "\n" not in text.replace("\r\n", ""))
        check("ini float", "PanelWidth=640.000000\r\n" in text)
        check("ini bool", "bShowIcons=False\r\n" in text)
        check("ini FLinearColor linear", "Accent=(R=1.000000,G=0.000000,B=0.000000,A=1.000000)" in text)
        check("ini struct", "Offset=(X=64.000000,Y=32.000000)" in text)
        check("ini enum", "Ease=OutBack" in text)
        check("ini keeps the override", "FadeSeconds=0.400000" in text)
        check("ini other sections untouched", "[Other]\r\nA=1" in text and "GameEngine=x" in text)
        check("ini keys inside their section", text.index("Ease=OutBack") < text.index("[Other]"))
        check("header untouched by ini target", header.read_text(encoding="utf-8") == HEADER)
        again = run()
        check("second ini run: nothing left", "\n0 change(s)" in again)

        # A fresh section when the class has none.
        ini.write_bytes(b"[/Script/Engine.Engine]\nGameEngine=x")
        run("--write")
        text = ini.read_text(encoding="utf-8")
        check("new section with the module name", "[/Script/HudExample.HudSettings]\nPanelWidth=640.000000\n" in text)
        check("text before the new section kept", text.startswith("[/Script/Engine.Engine]\nGameEngine=x\n"))

        # Header target.
        ini.write_bytes(INI.encode())
        out = run("--target", "header", "--write")
        h = header.read_text(encoding="utf-8")
        check("header float", "float PanelWidth = 640.f;" in h)
        check("header bool", "bool bShowIcons = false;" in h)
        check("header keeps the FColor form", "FLinearColor Accent = FLinearColor(FColor(0xFF, 0x00, 0x00));" in h)
        check("header linear colour", "FLinearColor Fill = FLinearColor(0.004f, 0.004f, 0.004f, 0.902f);" in h)
        check("header brace init kept", "FVector2D Offset{64.f, 32.f};" in h)
        check("header enum", "EHudEase Ease = EHudEase::OutBack;" in h)
        check("header adds a missing default", "float Delay = 0.1f;" in h)
        check("header non-Config class", "float Segments = 12.f;" in h)
        check("header comment after a default kept", "float FadeSeconds = 0.4f;   // overridden in DefaultGame.ini" in h)
        check("ini override flagged", "FadeSeconds: Config/DefaultGame.ini overrides it" in out)
        check("ini untouched by header target", ini.read_bytes() == INI.encode())
        again = run("--target", "header")
        check("second header run: nothing left", "\n0 change(s)" in again)
    finally:
        shutil.rmtree(project, ignore_errors=True)
    print(f"\n{len(failures)} failed" if failures else "\nall passed")
    sys.exit(len(failures))


if __name__ == "__main__":
    main()
