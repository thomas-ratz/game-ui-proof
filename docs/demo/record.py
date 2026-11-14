"""Records the README demo: drives a real Chrome over CDP through preview pages, captures frames with timestamps,
adds captions and highlights, writes <name>.gif and <name>.mp4. Needs Chrome, ffmpeg, Pillow and
`pip install websockets`.

    python docs/demo/record.py        # the tour of docs/demo/* -> docs/demo/demo.gif/.mp4

The tour runs in a throwaway project built from this repo's kit and demo pages, removed afterwards; saving writes only
into that copy.
"""
import asyncio, base64, io, json, shutil, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
import websockets
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[2]
OUT, NAME = REPO / "docs/demo", "demo"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
W, H, SERVE_PORT, CDP_PORT = 1600, 900, 8799, 9333
PAGES = ["hud", "pause", "dialogue", "transition"]
UI_FONT, CODE_FONT = r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\consolab.ttf"
ACCENT = (255, 209, 102)
frames = []  # dicts: t, image (PIL), caption, step, box


class Cdp:
    def __init__(self, ws): self.ws, self.n = ws, 0
    async def call(self, method, **params):
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg: raise RuntimeError(msg["error"])
                return msg.get("result", {})
    async def js(self, code):
        r = await self.call("Runtime.evaluate", expression=code, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r: raise RuntimeError(r["exceptionDetails"])
        return r["result"].get("value")


ROW = """((group, key) => document.querySelector(`#controls .row[data-group="${group}"][data-key="${key}"]`))"""


class Tour:
    def __init__(self, cdp): self.cdp, self.step, self.box = cdp, "", None

    async def snap(self, caption):
        r = await self.cdp.call("Page.captureScreenshot", format="png")
        box = await self.cdp.js(f"(() => {{ const e = {self.box}; if (!e) return null; const r = e.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; }})()") if self.box else None
        frames.append({"t": time.perf_counter(), "image": Image.open(io.BytesIO(base64.b64decode(r["data"]))).convert("RGB"),
                       "caption": caption, "step": self.step, "box": box})

    async def hold(self, seconds, caption):
        end = time.perf_counter() + seconds
        while time.perf_counter() < end: await self.snap(caption)

    async def open(self, url, step):
        self.step, self.box = step, None
        await self.cdp.call("Page.navigate", url=f"http://127.0.0.1:{SERVE_PORT}/{url}")
        for _ in range(80):
            await asyncio.sleep(0.15)
            if await self.cdp.js("document.readyState === 'complete' && (!!document.getElementById('save-status') || document.contentType.startsWith('image'))"): break
        await asyncio.sleep(0.4)

    async def show(self, element):
        await self.cdp.js(f"({element}).scrollIntoView({{block:'center'}})")

    async def slide(self, group, key, start, end, seconds, caption):
        await self.show(f"{ROW}('{group}','{key}')")
        t0 = time.perf_counter()
        while True:
            k = min(1, (time.perf_counter() - t0) / seconds); v = start + (end - start) * k * k * (3 - 2 * k)
            await self.cdp.js(f"(() => {{ const r = {ROW}('{group}','{key}').querySelector('input[type=range]'); r.value = {v}; r.dispatchEvent(new Event('input')); }})()")
            await self.snap(caption)
            if k >= 1: break

    async def colour(self, group, key, hexes, caption):
        await self.show(f"{ROW}('{group}','{key}')")
        for h in hexes:
            await self.cdp.js(f"(() => {{ const p = {ROW}('{group}','{key}').querySelector('input[type=color]'); p.value = '{h}'; p.dispatchEvent(new Event('input')); }})()")
            await self.hold(0.12, caption)

    async def click(self, element):
        await self.cdp.js(f"({element}).click()")

    async def variant(self, letter):
        await self.click(f"[...document.querySelectorAll('.variants button')].find(b => b.textContent.startsWith('{letter} '))")

    async def hover(self, element):
        await self.cdp.js(f"({element}).dispatchEvent(new PointerEvent('pointerenter'))")

    async def unhover(self, element):
        await self.cdp.js(f"({element}).dispatchEvent(new PointerEvent('pointerleave'))")

    async def at_stage(self, event, sx, sy):
        """Send a mouse/pointer event to the stage at stage pixel (sx, sy)."""
        await self.cdp.js(f"""(() => {{ const s = document.getElementById('stage'), r = s.getBoundingClientRect(), k = r.width / s.width;
            s.dispatchEvent(new {'MouseEvent' if event == 'click' else 'PointerEvent'}('{event}', {{ bubbles: true, clientX: r.left + {sx} * k, clientY: r.top + {sy} * k }})); }})()""")

    async def key(self, key, kind="keydown"):
        await self.cdp.js(f"document.body.dispatchEvent(new KeyboardEvent('{kind}', {{ key: '{key}', bubbles: true }}))")

    async def save(self):
        await self.show("document.querySelector('.actions')")
        await self.click("[...document.querySelectorAll('.actions button')].find(b => b.textContent === 'Save')")


async def tour(t):
    await t.open("docs/mockups/hud/?s=explore&v=a", "1 · HUD")
    await t.hold(1.5, "The agent drew your HUD over a screenshot of your game")
    await t.slide("Hud", "CellSize", 28, 44, 1.0, "You drag sliders until it feels right")
    await t.colour("theme: Hud", "cell_full", ["#ff5d6c", "#ff8a4c", "#ffc93c", "#8bd450", "#4fd1c5"], "Every colour, size and font the build will use")
    await t.hold(0.4, "Every colour, size and font the build will use")
    slot = f"{ROW}('Hud','SlotSize')"
    await t.show(slot)
    t.box = slot
    await t.hover(slot)
    await t.hold(1.8, "Hover a value to see what it changes")
    await t.unhover(slot)
    t.box = None
    await t.at_stage("click", 150, 144)  # the coin count
    t.box = "document.querySelector('#controls .row.found')"
    await t.show(t.box)
    await t.hold(1.8, "Click the game to find the values behind it")
    t.box = "document.getElementById('compare')"
    await t.key(" ")
    await t.hold(1.4, "Hold Space to compare with the saved values")
    await t.key(" ", "keyup")
    await t.hold(0.6, "Hold Space to compare with the saved values")
    t.box = "document.getElementById('zoom')"
    await t.at_stage("pointermove", 120, 110)
    await t.key("z")
    await t.hold(1.8, "Press Z to see it at real size")
    await t.key("z"); await t.key("z")
    t.box = None

    await t.open("docs/mockups/pause/?s=browse&v=a", "2 · Menus")
    t.box = "document.querySelector('.variants')"
    await t.hold(1.3, "The agent proposes a few layouts to choose from")
    await t.variant("b"); await t.hold(1.1, "The agent proposes a few layouts to choose from")
    await t.variant("c"); await t.hold(1.0, "The agent proposes a few layouts to choose from")
    await t.variant("b")
    t.box = "document.querySelector('.recommend')"
    await t.hold(2.2, "…and recommends one, with its reason")

    await t.open("docs/mockups/dialogue/?s=typing&v=a", "3 · Dialogue")
    await t.hold(1.2, "Dialogue boxes type at the real speed")
    await t.slide("DialogueBox", "CharsPerSecond", 30, 70, 0.9, "Dialogue boxes type at the real speed")
    await t.variant("b")
    t.box = "document.querySelector('.variants')"
    await t.hold(1.6, "A speech bubble instead? One click")

    await t.open("docs/mockups/transition/?s=clear&v=a", "4 · Transitions")
    await t.hold(2.3, "Transitions and screen effects, at real speed")
    await t.show(f"{ROW}('Preview','ReduceMotion')")
    t.box = f"{ROW}('Preview','ReduceMotion')"
    await t.click(f"{ROW}('Preview','ReduceMotion').querySelector('input')")
    await t.hold(2.0, "Accessibility: see what Reduce Motion turns it into")

    await t.open("docs/mockups/pause/sheet.png", "5 · Review")
    await t.hold(2.4, "One review sheet: every state of every variant")

    await t.open("docs/mockups/pause/?s=open&v=b", "6 · Approve")
    await t.slide("PauseMenu", "ItemGap", 20, 28, 0.6, "Happy? Press Save")
    await t.save()
    t.box = "document.getElementById('save-status')"
    await t.hold(1.8, "Save writes values.json, the approved spec")


def end_card(values_path, label):
    """The saved values.json as a code card: proof that tuning became a file."""
    text = json.dumps(json.loads(values_path.read_text(encoding="utf-8")), indent=2).splitlines()
    img = Image.new("RGB", (W, H), (18, 19, 26))
    d = ImageDraw.Draw(img)
    code, head = ImageFont.truetype(CODE_FONT, 22), ImageFont.truetype(UI_FONT, 30)
    d.text((80, 60), label, font=head, fill=ACCENT)
    y = 120
    for line in text[:24]:
        d.text((80, y), line, font=code, fill=(220, 225, 235)); y += 26
    if len(text) > 24: d.text((80, y), "  …", font=code, fill=(150, 155, 165))
    return img


def decorate(f):
    img, d = f["image"], ImageDraw.Draw(f["image"], "RGBA")
    if f["box"]:
        x, y, w, h = f["box"]
        d.rounded_rectangle([x - 6, y - 6, x + w + 6, y + h + 6], radius=8, outline=ACCENT + (255,), width=4)
    if f["step"]:
        sf = ImageFont.truetype(UI_FONT, 26)
        sw = d.textlength(f["step"], font=sf)
        d.rounded_rectangle([24, H - 74, 24 + sw + 32, H - 30], radius=10, fill=ACCENT + (255,))
        d.text((40, H - 70), f["step"], font=sf, fill=(20, 20, 24))
    font = ImageFont.truetype(UI_FONT, 30)
    w = d.textlength(f["caption"], font=font)
    # Centred on the stage: at its top, clear of dialogue boxes and the save toast; under the code on the end card.
    x, y = (img.width - 360 - w) / 2, img.height - 90 if f.get("bottom") else 92
    d.rounded_rectangle([x - 22, y - 12, x + w + 22, y + 44], radius=10, fill=(15, 15, 18, 235))
    d.text((x, y), f["caption"], font=font, fill=(255, 255, 255))
    return img


async def record(root, tour):
    profile = tempfile.mkdtemp()
    server = subprocess.Popen([sys.executable, "docs/mockups/kit/serve.py", "--port", str(SERVE_PORT)], cwd=root,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={CDP_PORT}", f"--user-data-dir={profile}",
                               "--hide-scrollbars", "--force-device-scale-factor=1", f"--window-size={W},{H + 200}", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try: tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json")); break
            except OSError: time.sleep(0.2)
        ws_url = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")
        async with websockets.connect(ws_url, max_size=50_000_000) as ws:
            cdp = Cdp(ws)
            await cdp.call("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=1, mobile=False)
            await cdp.call("Page.enable")
            await tour(Tour(cdp))
    finally:
        chrome.terminate(); server.terminate(); chrome.wait(10); server.wait(10)
        shutil.rmtree(profile, ignore_errors=True)


def main():
    root, feature = Path(tempfile.mkdtemp()), "pause"
    shutil.copytree(REPO / "skills/ui-preview/assets/kit", root / "docs/mockups/kit")
    shutil.copy(REPO / "docs/demo/scene.js", root / "docs/mockups/scene.js")
    for page in PAGES: shutil.copytree(REPO / "docs/demo" / page, root / "docs/mockups" / page)
    subprocess.run([sys.executable, "docs/mockups/kit/shots.py", "pause"], cwd=root, check=True, capture_output=True)
    values = root / "docs/mockups" / feature / "values.json"
    try:
        asyncio.run(record(root, tour))
        card, t = end_card(values, f"docs/mockups/{feature}/values.json"), frames[-1]["t"] + 0.1
        for i in range(36):
            frames.append({"t": t + i * 0.1, "image": card.copy(), "caption": "apply_godot.py / apply_uss.py write it into your engine",
                           "step": "7 · Build", "box": None, "bottom": True})
    finally:
        shutil.rmtree(root, ignore_errors=True)
    write()


def write():
    framedir = OUT / f"{NAME}_frames"; shutil.rmtree(framedir, ignore_errors=True); framedir.mkdir(parents=True)
    concat = []
    for i, f in enumerate(frames):
        p = framedir / f"{i:04d}.png"; decorate(f).save(p)
        nxt = frames[i + 1]["t"] if i + 1 < len(frames) else f["t"] + 1.5
        concat += [f"file '{p.as_posix()}'", f"duration {max(0.02, nxt - f['t']):.3f}"]
    concat.append(f"file '{(framedir / f'{len(frames) - 1:04d}.png').as_posix()}'")
    listing = OUT / f"{NAME}_frames.txt"; listing.write_text("\n".join(concat))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-crf", "20", str(OUT / f"{NAME}.mp4")], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(OUT / f"{NAME}.mp4"), "-vf",
                    "fps=15,scale=1200:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=192[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
                    str(OUT / f"{NAME}.gif")], check=True)
    shutil.rmtree(framedir); listing.unlink()
    print("frames", len(frames), "seconds", round(frames[-1]["t"] - frames[0]["t"] + 1.5, 1))


main()
