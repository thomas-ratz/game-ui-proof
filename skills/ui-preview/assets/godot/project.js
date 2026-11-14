// Once per Godot project: copy to <mockups>/kit/project.js; pages load it after godot_theme.js.
GodotTheme.configure({
  // theme: "res://ui/theme.tres",  // default: gui/theme/custom in project.godot
  fonts: { "res://fonts/body.ttf": "Body" },  // each theme font's path -> its @font-face family in project.css
  defaultFont: "Body",  // text whose type has no font, and a theme with no default_font
  // The keys and buttons bound to each action in Project Settings > Input Map, per device the preview offers.
  glyphs: {
    keyboard: { ui_accept: "ENTER", ui_cancel: "ESC", ui_pause: "ESC" },
    xbox: { ui_accept: ["face", "A"], ui_cancel: ["face", "B"], ui_pause: ["pill", "MENU"] },
    playstation: { ui_accept: ["face", "cross"], ui_cancel: ["face", "circle"], ui_pause: ["pill", "OPTIONS"] },
  },
  capInk: "#e8e8e8", capLetter: "#202020",  // key caps: face and letter
});
