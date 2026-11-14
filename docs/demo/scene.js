// The neutral demo level shared by every demo page: a procedural pixel-art platformer (no game's art).
// Demo.backdrop() draws it once at 480x270; Demo.draw(ctx) paints it scaled 4x onto the 1920x1080 stage.
const Demo = (() => {
const PX = 4; // the backdrop is drawn at 480x270 and scaled 4x
const SKY = [["#2b3a67", 0], ["#3d5a8a", 70], ["#6b8fb5", 140], ["#a7c4d9", 200]];

function rng(seed) { return () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646; }

/** The level behind the HUD, drawn once: sky bands, two mountain ranges, clouds, a tiled floor, platforms, a hero. */
function backdrop() {
  const c = document.createElement("canvas"); c.width = 480; c.height = 270;
  const g = c.getContext("2d"), r = rng(7);
  for (const [col, y] of SKY) { g.fillStyle = col; g.fillRect(0, y, 480, 270 - y); }
  const range = (col, base, amp, step) => {
    g.fillStyle = col; g.beginPath(); g.moveTo(0, 270);
    for (let x = 0, h = base; x <= 480; x += step) { h = Math.max(base - amp, Math.min(base + 10, h + (r() - 0.5) * amp)); g.lineTo(x, Math.round(h)); }
    g.lineTo(480, 270); g.fill();
  };
  range("#5b6f9a", 150, 50, 16); range("#465780", 175, 36, 12);
  g.fillStyle = "#e9f1f7";
  for (const [x, y, w] of [[40, 40, 46], [190, 26, 60], [330, 52, 40], [420, 30, 30]]) {
    g.fillRect(x, y, w, 6); g.fillRect(x + 6, y - 5, w - 16, 5); g.fillRect(x + 14, y - 9, w - 32, 4);
  }
  const tile = (x, y, top) => {
    g.fillStyle = "#6b4a3a"; g.fillRect(x, y, 16, 16);
    g.fillStyle = "#7d5846"; g.fillRect(x + 2, y + 6, 5, 3); g.fillRect(x + 10, y + 11, 4, 2);
    if (top) { g.fillStyle = "#59b85a"; g.fillRect(x, y, 16, 4); g.fillStyle = "#83d66a"; g.fillRect(x, y, 16, 1); g.fillRect(x + 3, y + 4, 2, 1); }
  };
  for (let x = 0; x < 480; x += 16) for (let y = 222; y < 270; y += 16) tile(x, y, y === 222);
  for (const [x0, y, n] of [[96, 166, 4], [272, 136, 5], [400, 182, 3]]) for (let i = 0; i < n; i++) tile(x0 + i * 16, y, true);
  g.fillStyle = "#f4c542";
  for (const [x, y] of [[300, 120], [316, 120], [332, 120], [120, 150]]) { g.fillRect(x, y, 6, 8); g.fillStyle = "#fbe38a"; g.fillRect(x + 1, y + 1, 2, 4); g.fillStyle = "#f4c542"; }
  const hero = ["..1111..", ".122221.", ".123321.", ".122221.", "..1111..", ".144441.", "14455441", ".144441.", "..4..4..", ".55..55."];
  const pal = { 1: "#1d1d2b", 2: "#ffd8b5", 3: "#1d1d2b", 4: "#e2574c", 5: "#3b3b52" };
  hero.forEach((row, y) => [...row].forEach((k, x) => { if (pal[k]) { g.fillStyle = pal[k]; g.fillRect(150 + x * 2, 202 + y * 2, 2, 2); } }));
  return c;
}

  let level;
  const draw = ctx => { level ??= backdrop(); ctx.imageSmoothingEnabled = false; ctx.drawImage(level, 0, 0, 480 * PX, 270 * PX); };
  return { draw, hero: [150 + 8, 202 + 10].map(v => v * PX) };
})();
