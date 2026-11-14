extends Control
## The script the template page's "HealthBar" group writes into (apply_godot.py).

@export_group("HealthBar")
@export var x := 32
@export var y := 32
@export var segment_width := 24
@export var segment_height := 16
@export var gap := 4
@export var segments := 5
@export var pulse_seconds := 0.6
@export var style := "flat"
