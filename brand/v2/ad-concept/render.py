"""Render ad.html frame by frame (30fps) to frames/ or preview times given on argv."""
import os, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
HERE = Path(__file__).resolve().parent
FPS, DUR = 30, 30.0
times = [float(x) for x in sys.argv[1:]]
out = HERE / ("preview" if times else "frames"); out.mkdir(exist_ok=True)
seller = HERE / "seller"
nseller = len(list(seller.glob("*.jpg"))) if seller.is_dir() else 0
with sync_playwright() as p:
    b = p.chromium.launch(args=["--allow-file-access-from-files", "--no-sandbox"])
    pg = b.new_page(viewport={"width": 1920, "height": 1080})
    pg.goto((HERE / "ad.html").as_uri()); pg.wait_for_load_state("networkidle")
    pg.evaluate("document.fonts.ready.then(()=>Promise.all([...document.images].map(i=>i.decode().catch(()=>0))))")
    pg.evaluate(f"window.leftFrames={nseller}")
    seq = times or [i / FPS for i in range(int(FPS * DUR))]
    for i, t in enumerate(seq):
        pg.evaluate(f"draw({t})")
        name = f"t{t:05.2f}.jpg" if times else f"{i:05d}.jpg"
        pg.screenshot(path=str(out / name), type="jpeg", quality=92)
    b.close()
print(len(seq), "frames")
