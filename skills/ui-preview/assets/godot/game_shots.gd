extends SceneTree
# Backdrops for a ui-preview page: a level with the UI hidden, and (WITH_UI) once more with today's UI shown.
# Run windowed (a --headless run renders nothing), from the project root:
#   godot --path . --script docs/mockups/<feature>/game_shots.gd -- <out dir> [res://path/level.tscn]
# The shots are the window's size: the project's viewport (display/window/size/viewport_*), which is the preview's
# stage, unless --resolution WxH says otherwise.
# Keep the run away from real saves: point user:// at an empty temp folder for it (Windows: APPDATA=<dir>,
# Linux: XDG_DATA_HOME=<dir>, macOS: HOME=<dir>).
# To reach a spot the level doesn't start at, move the player or open a menu in run() before the shots.

const LEVEL := "res://main.tscn"  # or the second argument after --
const UI_NODE := "UI"  # the CanvasLayer or Control to hide: an autoload's name, or a node's name in the level
const SETTLE_FRAMES := 60  # let spawns, cameras and tweens settle
const WITH_UI := true

var out_dir := "."
var level := LEVEL


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() > 0:
		out_dir = args[0]
	if args.size() > 1:
		level = args[1]
	DirAccess.make_dir_recursive_absolute(out_dir)
	run.call_deferred()


func run() -> void:
	if change_scene_to_file(level) != OK:
		push_error("can't load " + level)
		quit(1)
		return
	await frames(SETTLE_FRAMES)
	var ui := root.get_node_or_null(UI_NODE)
	if ui == null:
		ui = current_scene.find_child(UI_NODE, true, false)
	if ui == null:
		push_warning("no node named %s: the clean shot shows the UI" % UI_NODE)
	var base := level.get_file().get_basename()
	if ui:
		ui.set("visible", false)
	await frames(2)
	await shot(base)
	if WITH_UI and ui:
		ui.set("visible", true)
		await frames(2)
		await shot(base + "_ui")
	quit(0)


func frames(n: int) -> void:
	for i in n:
		await process_frame


func shot(file: String) -> void:
	await RenderingServer.frame_post_draw
	var img := root.get_texture().get_image()
	var stage := Vector2i(ProjectSettings.get_setting("display/window/size/viewport_width"),
		ProjectSettings.get_setting("display/window/size/viewport_height"))
	if img.get_size() != stage:
		push_warning("shot is %s but the stage is %s: run with --resolution %dx%d" % [img.get_size(), stage, stage.x, stage.y])
	var path := out_dir.path_join(file + ".png")
	img.save_png(path)
	print("saved ", path)
