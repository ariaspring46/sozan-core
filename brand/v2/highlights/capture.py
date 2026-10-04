"""Screenshots of the local panel with the lab test tenant (390x844 @3x, dark)."""
import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
SP = Path(os.environ.get("SHOTS_WORK", "."))  # folder holding the lab-token file
OUT = Path(__file__).resolve().parent / "shots"; OUT.mkdir(exist_ok=True)
TOKEN = (SP / "lab-token").read_text().strip()
BASE = "http://127.0.0.1:3000"
SARA = "/inbox/" + os.environ.get("SHOTS_THREAD", "")
ORDER = "/p/" + os.environ.get("SHOTS_ORDER", "")
def typ(ph, text):
    return lambda pg: (pg.get_by_placeholder(ph).first.click(), pg.keyboard.type(text, delay=5))
def click(text):
    return lambda pg: pg.get_by_text(text, exact=True).first.click()
def scroll_to(text, up=12):
    def run(pg):
        pg.get_by_text(text, exact=True).first.scroll_into_view_if_needed()
        pg.evaluate(f"(() => {{ const el=[...document.querySelectorAll('*')].find(e=>e.textContent.trim()==={text!r}); let s=el; while(s&&s.scrollHeight<=s.clientHeight+2) s=s.parentElement; (s||document.scrollingElement).scrollTop -= {up}; }})()")
    return run
def select(label_text, option):
    return lambda pg: pg.locator("select").filter(has=pg.locator(f"option:text-is('{option}')")).first.select_option(label=option)
SHOTS = {
  "login": ("/login", []),
  "onboard": ("/onboard", []),
  "chat": ("/chat", []),
  "chat-post": ("/chat", [typ("به سوزان بگو", "برای انگشتر نقره یه پست اینستاگرام بساز")]),
  "chat-shop": ("/chat", [typ("به سوزان بگو", "یه فروشگاه برای زیورآلات نقره بساز؛ رنگ‌ها کرم و مسی، حس گرم و ساده")]),
  "shop-domain": ("/shop", [click("بعد از ساخت سایت")]),
  "shop-domain-typed": ("/shop", [click("بعد از ساخت سایت"), lambda pg: pg.get_by_placeholder("shop.example.com").fill("noghreh-shop.ir")]),
  "inventory": ("/more/inventory", []),
  "inventory-add": ("/more/inventory", [click("افزودن کالا")]),
  "studio": ("/studio", []),
  "studio-captions": ("/studio", [lambda pg: pg.evaluate("(()=>{const s=[...document.querySelectorAll('*')].filter(e=>e.scrollHeight>e.clientHeight+50&&getComputedStyle(e).overflowY!='visible');(s.pop()||document.scrollingElement).scrollTop=99999})()")]),
  "inbox": ("/inbox", []),
  "thread": (SARA, []),
  "sales": ("/sales", []),
  "order": (ORDER, []),
  "settings-pay": ("/more/settings", [select("درگاه پرداخت", "زرین‌پال"), scroll_to("فروشگاه و پرداخت", 12)]),
  "wallet": ("/more/wallet", []),
  "channels": ("/more/channels", []),
  "channels-telegram": ("/more/channels", [select("پلتفرم", "تلگرام")]),
  "channels-whatsapp": ("/more/channels", [select("پلتفرم", "واتساپ")]),
}
only = sys.argv[1:] or list(SHOTS)
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox"])
    for name in only:
        route, actions = SHOTS[name]
        ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, color_scheme="dark", locale="fa-IR", is_mobile=True, has_touch=True)
        boot = "localStorage.setItem('sozan_theme','dark');"
        if name != "login":
            boot += f"localStorage.setItem('sozan_token','{TOKEN}');localStorage.setItem('sozan_onboarded','1');"
        ctx.add_init_script(boot)
        pg = ctx.new_page()
        pg.goto(BASE + route, wait_until="networkidle", timeout=120000)
        pg.add_style_tag(content="nextjs-portal{display:none!important} *{caret-color:transparent!important}")
        pg.wait_for_timeout(1500)
        for act in actions:
            act(pg); pg.wait_for_timeout(700)
        pg.wait_for_timeout(1500)
        pg.screenshot(path=str(OUT / f"{name}.png"))
        print(name)
        ctx.close()
    b.close()
