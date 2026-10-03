"""content.json را به عکس‌های ۱۰۸۰×۱۹۲۰ استوری (و جلد هر هایلایت) در out/ تبدیل می‌کند.

اجرا: python3 render.py [content.json]   (به playwright و chromium نیاز دارد؛ CHROME_PATH اختیاری)
"""
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
src = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "content.json"
data = json.loads(src.read_text(encoding="utf-8"))
out = HERE / "out"
out.mkdir(exist_ok=True)
html = (HERE / "template.html").read_text(encoding="utf-8").replace(
    "<script>", "<script>window.DATA=" + json.dumps(data, ensure_ascii=False) + ";", 1
)
page_file = HERE / "_render.html"
page_file.write_text(html, encoding="utf-8")
with sync_playwright() as p:
    kw = {"args": ["--allow-file-access-from-files", "--no-sandbox"]}
    if os.environ.get("CHROME_PATH"):
        kw["executable_path"] = os.environ["CHROME_PATH"]
    browser = p.chromium.launch(**kw)
    page = browser.new_page(viewport={"width": 1200, "height": 2000})
    page.goto(page_file.as_uri())
    page.wait_for_timeout(800)
    for el in page.locator("section.s").all():
        name = el.get_attribute("data-name")
        el.screenshot(path=str(out / f"{name}.png"))
        print(name)
    browser.close()
page_file.unlink()
