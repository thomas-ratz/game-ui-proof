#pragma once

#include "CoreMinimal.h"
#include "Engine/DeveloperSettings.h"
#include "HudPanelSettings.generated.h"

/** How the panel's bar fills. */
UENUM(BlueprintType)
enum class EHudFill : uint8
{
	Solid,
	Segmented UMETA(DisplayName = "Segmented")
};

/**
 * The stamina panel's layout (Project Settings > Game > Hud Panel). Lengths are px on the 1920 x 1080 canvas.
 * The panel's colours come from the DT_HudStyle DataTable.
 */
UCLASS(Config = Game, DefaultConfig, meta = (DisplayName = "Hud Panel"))
class HUDEXAMPLE_API UHudPanelSettings : public UDeveloperSettings
{
	GENERATED_BODY()

public:
	/** The panel's top-left corner. */
	UPROPERTY(Config, EditAnywhere, Category = "Layout")
	FVector2D Position = FVector2D(48.f, 48.f);

	UPROPERTY(Config, EditAnywhere, Category = "Layout", meta = (ClampMin = "200", ClampMax = "1000"))
	float Width = 520.f;

	/** The title's size (px). */
	UPROPERTY(Config, EditAnywhere, Category = "Text", meta = (ClampMin = "12", ClampMax = "72"))
	float TitleSize = 32.f;

	UPROPERTY(Config, EditAnywhere, Category = "Bar")
	EHudFill Fill = EHudFill::Segmented;

	UPROPERTY(Config, EditAnywhere, Category = "Bar", meta = (ClampMin = "2", ClampMax = "20"))
	int32 Segments = 8;

	UPROPERTY(Config, EditAnywhere, Category = "Bar")
	FLinearColor TrackColor = FLinearColor(0.f, 0.f, 0.f, 0.4f);
};
