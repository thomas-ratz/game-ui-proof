using Godot;

// The script the Godot example page's "ConfirmDialog" group writes into (apply_godot.py).
public partial class ConfirmDialog : PanelContainer
{
    [ExportGroup("ConfirmDialog")]
    [Export] public int Width { get; set; } = 480;
    [Export] public int Height { get; set; } = 220;
    [Export] public int Padding { get; set; } = 24;
    [Export] public float OpenSeconds { get; set; } = 0.25f;
}
