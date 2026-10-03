// Mobile shop-page probe: the «فروشگاه» tab on a phone is only the live site preview. Nothing is written: the storefront
// is a fake served by the browser (page.route) with the real preview beacon injected, and every /shop write
// (chat, undo, image, build) is a browser stub that keeps a tiny pending/undo state machine.
//   PANEL=http://127.0.0.1:3998 API=http://127.0.0.1:8014 TOKEN_FILE=~/shop-lab/token OUT=./shop-mobile-shots \
//   BEACON=frontend/public/sozan-preview-beacon.js node tools/ui_shop_mobile_probe.mjs
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const HOME = process.env.HOME;
const BASE = process.env.PANEL || "http://127.0.0.1:3998";
const API = process.env.API || "http://127.0.0.1:8014";
const TOKEN = fs.readFileSync((process.env.TOKEN_FILE || path.join(HOME, "shop-lab/token")).replace(/^~/, HOME), "utf8").trim();
const OUT = process.env.OUT || path.join(HOME, "shop-lab/mobile-shots");
const BEACON = fs.readFileSync(process.env.BEACON || path.join(path.dirname(new URL(import.meta.url).pathname), "../frontend/public/sozan-preview-beacon.js"), "utf8");
const HOST = "qa-shop.sozan-core.ir";
fs.mkdirSync(OUT, { recursive: true });
const findings = [];
const rec = (id, ok, detail) => {
  findings.push({ id, ok, detail });
  console.log(`${ok ? "OK  " : "FAIL"} ${id} ${detail ?? ""}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const isPathname = (url, p) => {
  try {
    return new URL(url).pathname === p;
  } catch {
    return false;
  }
};
// 1x1 PNG, so <img> and background-image both decode
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");

const PAGE = (body) => `<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>فروشگاه آزمایشی</title>
<style>body{margin:0;font-family:sans-serif;background:#faf7f2}header{display:flex;gap:8px;padding:6px 12px;background:#fff}header a{padding:14px 10px;color:#333}
.hero{position:relative;height:260px;background:url(/images/hero.png) center/cover}.veil{position:absolute;inset:0;background:linear-gradient(transparent,rgba(0,0,0,.35))}
.hero h1{position:absolute;bottom:20px;right:16px;margin:0;color:#fff}.card{padding:16px}.card img{width:100%;height:200px;object-fit:cover}button{padding:14px 22px}</style></head><body>${body}
<div style="height:1400px"></div><script src="/sozan-preview-beacon.js?v=live2" defer></script></body></html>`;
const HOME_HTML = PAGE(`<header><a href="/products" id="nav-products">کالاها</a><a href="/cart">سبد</a></header>
<section class="hero" id="hero"><div class="veil" id="veil"></div><p id="hero-copy" style="position:absolute;top:24px;right:16px;margin:0;color:#fff">مد و کفش</p><h1 id="title">زیورآلات دست‌ساز نیشابور</h1></section>
<p id="lede" style="padding:0 16px">هر قطعه با دست ساخته می‌شود.</p>
<a class="card" id="nophoto" href="/products/p1" style="display:block;text-decoration:none;color:#222"><h3 id="nph">کیف چرمی</h3><span>۹۰۰٬۰۰۰ تومان</span></a>
<div class="card"><img id="prod" src="/_next/image?url=%2Fproducts%2Fa1.jpg&w=640&q=75" alt="انگشتر نقره"><h3 id="ptitle">انگشتر نقره</h3><button id="cta">مشاهده محصولات</button></div>`);
const PRODUCTS_HTML = PAGE(`<header><a href="/" id="nav-home">خانه</a></header><h1 id="all" style="padding:16px">همه کالاها</h1>`);

async function realShop() {
  const res = await fetch(`${API}/shop`, { headers: { Authorization: `Bearer ${TOKEN}` } });
  return res.json();
}

async function boot(browser, { w = 390, h = 844 } = {}) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 2, isMobile: w < 800, hasTouch: w < 800, locale: "fa-IR", ignoreHTTPSErrors: true });
  await ctx.addInitScript((t) => {
    localStorage.setItem("sozan_token", t);
    localStorage.setItem("sozan_onboarded", "1");
    window.__previewMsgs = [];
    window.addEventListener("message", (e) => {
      if (e.data && e.data.source === "sozan-preview") window.__previewMsgs.push(JSON.stringify(e.data.pick || e.data).slice(0, 200));
    });
  }, TOKEN);
  const S = { pending: 0, undo: 0, building: false, chats: [], images: [], undos: 0, builds: [], chatBuilds: [], bodies: [] };
  const cap = [];
  await ctx.route(`https://${HOST}/**`, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/sozan-preview-beacon.js") return route.fulfill({ status: 200, contentType: "application/javascript", body: BEACON });
    if (url.pathname === "/products") return route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: PRODUCTS_HTML });
    if (/\.(png|jpg)$/.test(url.pathname) || url.pathname.startsWith("/_next/image")) return route.fulfill({ status: 200, contentType: "image/png", body: PNG });
    return route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: HOME_HTML });
  });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 180)));
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource|ERR_/.test(m.text())) errors.push(m.text().slice(0, 180));
  });
  const json = (body) => ({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify(body) });
  await page.route(`${API}/**`, async (route) => {
    const req = route.request();
    const url = req.url();
    const method = req.method();
    const real = async () => realShop();
    const view = async (extra = {}) => {
      const base = await real();
      return {
        ...base,
        shop: { ...base.shop, status: S.building ? "running" : "ready", slug: "qa-shop", publicHost: HOST, url: `https://${HOST}`, pendingBuild: S.pending, undoDepth: S.undo },
        build: {
          ...(base.build || {}),
          status: S.building ? "running" : "ready",
          url: `https://${HOST}`,
          stepLabel: S.building ? "در حال طراحی ظاهر و چیدن کالاها…" : "",
          startedAt: S.building ? new Date(Date.now() - 38000).toISOString() : undefined,
          pipeline: S.building
            ? [
                { id: "archetype", label: "فهم نوع فروشگاه", state: "done" },
                { id: "DESIGN_CLOUD", label: "طراحی ظاهر", state: "active" },
                { id: "COPY_TEMPLATE", label: "ساخت صفحه‌ها", state: "wait" },
                { id: "DOCKER", label: "روشن کردن سایت", state: "wait" },
              ]
            : [],
        },
        ...extra,
      };
    };
    if (isPathname(url, "/shop") && method === "GET") return route.fulfill(json(await view()));
    if (isPathname(url, "/shop/chat") && method === "POST") {
      const body = JSON.parse(req.postData() || "{}");
      S.chats.push(body);
      await sleep(500);
      if (/از نو بساز/.test(body.text) && !body.confirm) {
        return route.fulfill(json(await view({ patched: false, preview: {}, needsConfirm: true, messages: [{ id: "rb", role: "assistant", kind: "ask", text: "از نو ساختن سایت فعلی را عوض می‌کند و «برگشت» پاک می‌شود. همین را بسازم؟" }] })));
      }
      if (/از نو بساز/.test(body.text) && body.confirm) {
        S.chatBuilds.push(body.text);
        return route.fulfill(json(await view({ patched: false, preview: {}, messages: [{ id: "rb2", role: "assistant", text: "ساخت فروشگاه شروع شد." }] })));
      }
      if (/نمی‌دانم/.test(body.text)) {
        return route.fulfill(json(await view({ patched: false, preview: {}, messages: [{ id: "q", role: "assistant", text: "منظورت کدام بخش است؟ بگو تا دقیق‌تر عوضش کنم." }] })));
      }
      S.pending += 1;
      S.undo += 1;
      const find = body.viewTarget || "";
      return route.fulfill(json(await view({
        patched: true,
        preview: find ? { find, replace: "زیورآلات نقرهٔ نیشابور" } : { reload: true },
        messages: [{ id: `a${S.undo}`, role: "assistant", text: "عوض کردم؛ همین‌طوری که می‌بینی. هر وقت راضی بودی «بیلد» را بزن." }],
      })));
    }
    if (isPathname(url, "/shop/undo") && method === "POST") {
      S.undos += 1;
      await sleep(300);
      if (S.undo > 0) {
        S.undo -= 1;
        S.pending = Math.max(0, S.pending - 1);
      }
      return route.fulfill(json(await view({ patched: true, reply: "به حالت قبل برگشت.", preview: { undo: true, to: S.undo } })));
    }
    if (isPathname(url, "/shop/image") && method === "POST") {
      const raw = req.postDataBuffer()?.toString("latin1") || "";
      S.images.push({ src: (/name="src"\r\n\r\n([^\r]*)/.exec(raw) || [])[1] || "", product: (/name="product"\r\n\r\n([^\r]*)/.exec(raw) || [])[1] || "", hasFile: /name="file"/.test(raw), bytes: raw.length });
      await sleep(400);
      S.pending += 1;
      S.undo += 1;
      return route.fulfill(json(await view({ patched: true, reply: "عکس بالای سایت عوض شد.", preview: { reload: true }, kind: "hero" })));
    }
    if (isPathname(url, "/shop/build") && method === "POST") {
      S.builds.push(JSON.parse(req.postData() || "{}"));
      S.building = true;
      setTimeout(() => {
        S.building = false;
        S.pending = 0;
        S.undo = 0;
      }, 3500);
      return route.fulfill(json({ result: { ok: true }, ...(await view()) }));
    }
    return route.continue();
  });
  await page.goto(`${BASE}/shop`, { waitUntil: "domcontentloaded" });
  await sleep(5500);
  const cdp = await ctx.newCDPSession(page);
  return { ctx, page, cdp, S, errors, cap };
}

const shopFrame = (page) => page.frames().find((f) => f.url().includes(HOST));
async function framePoint(page, selector, dx = 0.5, dy = 0.5) {
  const frame = shopFrame(page);
  const box = await page.locator("iframe").boundingBox();
  const inner = await frame.evaluate((sel) => {
    const el = document.querySelector(sel);
    const r = el.getBoundingClientRect();
    return { x: r.left, y: r.top, w: r.width, h: r.height };
  }, selector);
  return { x: box.x + inner.x + inner.w * dx, y: box.y + inner.y + inner.h * dy };
}
async function hold(cdp, { x, y }, ms = 800) {
  await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y }] });
  await sleep(ms);
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await sleep(250);
}
async function tapAt(cdp, { x, y }) {
  await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y }] });
  await sleep(60);
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await sleep(250);
}
async function swipe(cdp, from, to) {
  await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [from] });
  for (let i = 1; i <= 8; i += 1) {
    await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: from.x + ((to.x - from.x) * i) / 8, y: from.y + ((to.y - from.y) * i) / 8 }] });
    await sleep(40);
  }
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await sleep(300);
}
// the build button carries the pending count in its name («بیلد ۲») and says «در حال بیلد…» while it runs
const btn = (page, name) => (name === "بیلد" ? page.getByRole("button", { name: /^(در حال )?بیلد/ }) : page.getByRole("button", { name, exact: true }));
const enabled = async (page, name) => (await btn(page, name).count()) > 0 && (await btn(page, name).isEnabled());
const sheet = (page) => page.getByRole("dialog", { name: "ویرایش این بخش" });
const closeSheet = (page) => sheet(page).getByRole("button", { name: "بستن", exact: true }).click();
const shot = (page, name) => page.screenshot({ path: path.join(OUT, `${name}.png`) });

async function main() {
  const browser = await chromium.launch();
  const { ctx, page, cdp, S, errors } = await boot(browser);

  // 1) the phone page is only the site
  const layout = await page.evaluate(() => {
    const frame = document.querySelector("iframe");
    const r = frame?.getBoundingClientRect();
    return {
      frameH: Math.round(r?.height || 0),
      frameW: Math.round(r?.width || 0),
      vh: innerHeight,
      aside: Boolean(document.querySelector('aside[aria-label="ویرایش فروشگاه"]')),
      command: Boolean(document.querySelector("#shop-command")),
      textareas: document.querySelectorAll("textarea, input[type=text]").length,
      text: document.body.innerText.replace(/\s+/g, " "),
    };
  });
  await shot(page, "01-preview-only");
  rec("layout.preview-only", !layout.aside && !layout.command && layout.textareas === 0, `aside=${layout.aside} command=${layout.command} fields=${layout.textareas}`);
  rec("layout.preview-share", layout.frameH / layout.vh >= 0.6, `iframe ${layout.frameW}x${layout.frameH} of ${layout.vh}px (${Math.round((100 * layout.frameH) / layout.vh)}%)`);
  rec("layout.real-phone-width", Math.abs(layout.frameW - 390) <= 2, `iframe width ${layout.frameW} (a 390px phone shows the site at its own size)`);
  rec("layout.no-mode-or-tabs", !/(^| )طراحی( |$)|(^| )مرور( |$)|خانه کالاها سبد/.test(layout.text), "no design/browse toggle or page chips");
  rec("bar.two-buttons", (await btn(page, "بیلد").count()) === 1 && (await btn(page, "برگشت").count()) === 1, "«بیلد» and «برگشت» exist once");
  rec("bar.disabled-at-start", !(await enabled(page, "بیلد")) && !(await enabled(page, "برگشت")), "nothing to build or undo yet");
  rec("hint.shown-once", /انگشتت را رویش نگه دار/.test(layout.text), "first-time hold hint is visible");

  // 2) browsing inside the site: tapping a link navigates and opens nothing
  await tapAt(cdp, await framePoint(page, "#nav-products"));
  await sleep(1200);
  const nav = shopFrame(page).url();
  rec("browse.link-navigates", nav.endsWith("/products") || nav.includes("/products?"), nav);
  rec("browse.no-sheet-on-tap", (await sheet(page).count()) === 0, "a tap does not open the editor");
  await tapAt(cdp, await framePoint(page, "#nav-home"));
  await sleep(1200);

  // 3) a swipe scrolls and does not select
  const box = await page.locator("iframe").boundingBox();
  await swipe(cdp, { x: box.x + 200, y: box.y + 400 }, { x: box.x + 200, y: box.y + 150 });
  rec("browse.scroll-no-sheet", (await sheet(page).count()) === 0, "scrolling does not open the editor");
  await swipe(cdp, { x: box.x + 200, y: box.y + 150 }, { x: box.x + 200, y: box.y + 450 });

  // 4) hold on a link: opens the sheet and does not follow the link
  await hold(cdp, await framePoint(page, "#nav-products"));
  const afterHoldLink = shopFrame(page).url();
  rec("hold.link-selects-not-navigates", (await sheet(page).count()) === 1 && !afterHoldLink.includes("/products"), `${afterHoldLink} sheet=${await sheet(page).count()}`);
  await closeSheet(page);
  await sleep(300);

  // 5) hold on text: the sheet names it and the prompt reaches the edit endpoint with that text as the target
  await hold(cdp, await framePoint(page, "#title"));
  await shot(page, "02-sheet-text");
  const sheetText = (await sheet(page).count()) ? await sheet(page).innerText() : "";
  rec("hold.text-opens-sheet", /زیورآلات دست‌ساز نیشابور/.test(sheetText) && /تیتر/.test(sheetText), sheetText.replace(/\s+/g, " ").slice(0, 120));
  rec("hold.hint-dismissed", !/انگشتت را رویش نگه دار/.test(await page.evaluate(() => document.body.innerText)), "hint is gone after the first hold");
  // 5b) the keyboard: the sheet's own field stays visible and the site above it stays usable
  await page.locator("#shop-sheet-command").click();
  await page.setViewportSize({ width: 390, height: 520 });
  await sleep(900);
  const kb = await page.evaluate(() => {
    const input = document.querySelector("#shop-sheet-command").getBoundingClientRect();
    const frame = document.querySelector("iframe")?.getBoundingClientRect();
    return { vh: innerHeight, inputTop: Math.round(input.top), inputBottom: Math.round(input.bottom), frameH: Math.round(frame?.height || 0) };
  });
  await shot(page, "03b-keyboard");
  rec("keyboard.sheet-input-visible", kb.inputTop >= 0 && kb.inputBottom <= kb.vh, JSON.stringify(kb));
  await page.setViewportSize({ width: 390, height: 844 });
  await sleep(600);
  await page.locator("#shop-sheet-command").evaluate((el) => el.blur());

  await page.locator("#shop-sheet-command").fill("کوتاه‌ترش کن و اسم شهر بماند");
  await page.getByRole("button", { name: "بفرست" }).click();
  await sleep(1800);
  rec("edit.sent-with-target", S.chats.length === 1 && S.chats[0].viewTarget === "زیورآلات دست‌ساز نیشابور" && /کوتاه/.test(S.chats[0].text), JSON.stringify(S.chats[0] || {}).slice(0, 160));
  rec("edit.sheet-closes-and-notice", (await sheet(page).count()) === 0 && /عوض کردم/.test(await page.evaluate(() => document.body.innerText)), "result is shown over the preview");
  const patched = await shopFrame(page).evaluate(() => document.querySelector("#title")?.textContent || "");
  rec("edit.preview-patched", patched === "زیورآلات نقرهٔ نیشابور", patched);
  rec("bar.build-and-undo-enabled-after-edit", (await enabled(page, "بیلد")) && (await enabled(page, "برگشت")), "both buttons wake up after one edit");
  const badge = await btn(page, "بیلد").innerText();
  rec("bar.pending-count", /[1۱]/.test(badge), badge.replace(/\s+/g, " "));
  await shot(page, "03-after-edit");

  // 6) a question that is not an edit keeps the sheet open and shows the reply
  await hold(cdp, await framePoint(page, "#lede"));
  await page.locator("#shop-sheet-command").fill("نمی‌دانم چه بنویسم");
  await page.getByRole("button", { name: "بفرست" }).click();
  await sleep(1500);
  const stillOpen = (await sheet(page).count()) === 1;
  rec("edit.non-edit-reply-stays", stillOpen && /منظورت کدام/.test(await sheet(page).innerText()), "the model's question appears inside the sheet");
  await shot(page, "04-sheet-question");
  await closeSheet(page);
  await sleep(300);

  // 6b) a typed «از نو بساز» does not rebuild by itself: a confirm card with two buttons appears over the preview
  await hold(cdp, await framePoint(page, "#lede"));
  await page.locator("#shop-sheet-command").fill("فروشگاه را از نو بساز");
  await page.getByRole("button", { name: "بفرست" }).click();
  await sleep(1500);
  const askCard = page.getByText("همین را بسازم؟").first();
  const buildsBeforeAsk = S.chatBuilds.length;
  rec("rebuild.asks-first", (await askCard.count()) === 1 && S.chats[S.chats.length - 1].confirm !== true && (await sheet(page).count()) === 0, "card shown, sheet closed, nothing built");
  await shot(page, "04b-rebuild-confirm");
  await page.getByRole("button", { name: "انصراف" }).click();
  await sleep(300);
  rec("rebuild.cancel-dismisses", (await page.getByText("همین را بسازم؟").count()) === 0 && S.chatBuilds.length === buildsBeforeAsk, "cancel closes the card and builds nothing");
  await hold(cdp, await framePoint(page, "#lede"));
  await page.locator("#shop-sheet-command").fill("فروشگاه را از نو بساز");
  await page.getByRole("button", { name: "بفرست" }).click();
  await sleep(1500);
  await page.getByRole("button", { name: "تأیید" }).click();
  await sleep(1200);
  rec("rebuild.confirm-resends-with-flag", S.chats[S.chats.length - 1].confirm === true && S.chatBuilds.length === buildsBeforeAsk + 1, JSON.stringify(S.chats[S.chats.length - 1]));

  // 7) hold on the picture (an overlay sits on it): image sheet, upload goes to /shop/image with the picture's src
  const veilPoint = await framePoint(page, "#veil", 0.5, 0.3);
  await hold(cdp, veilPoint);
  const imgSheet = (await sheet(page).count()) ? await sheet(page).innerText() : "";
  if (!imgSheet) console.log("   diag: last preview messages", JSON.stringify(await page.evaluate(() => window.__previewMsgs.slice(-3))));
  await shot(page, "05-sheet-image");
  rec("hold.image-sheet", /عکس از گوشی/.test(imgSheet) && /با هوش مصنوعی/.test(imgSheet), imgSheet.replace(/\s+/g, " ").slice(0, 100));
  const before = S.images.length;
  await page.locator('input[type="file"]').setInputFiles({ name: "my.png", mimeType: "image/png", buffer: PNG });
  await sleep(1800);
  rec("image.uploaded-with-src", S.images.length === before + 1 && /hero\.png/.test(S.images[S.images.length - 1]?.src || "") && S.images[S.images.length - 1].hasFile, JSON.stringify(S.images[S.images.length - 1] || {}).slice(0, 140));
  rec("image.sheet-closes", (await sheet(page).count()) === 0, "after the swap");

  // 7b) words on top of the picture: the text can be edited AND the picture behind it can be swapped
  await hold(cdp, await framePoint(page, "#hero-copy"));
  const overText = (await sheet(page).count()) ? await sheet(page).innerText() : "";
  await shot(page, "05b-sheet-text-over-image");
  rec("hold.text-over-image-offers-both", /ثبت متن/.test(overText) && /عکس از گوشی/.test(overText) && /با هوش مصنوعی/.test(overText), overText.replace(/\s+/g, " ").slice(0, 110));
  let beforeCount = S.images.length;
  await page.locator('input[type="file"]').setInputFiles({ name: "x.png", mimeType: "image/png", buffer: PNG });
  await sleep(1500);
  rec("image.behind-text-swapped", S.images.length === beforeCount + 1 && /hero\.png/.test(S.images[S.images.length - 1]?.src || ""), JSON.stringify(S.images[S.images.length - 1] || {}).slice(0, 120));

  // 7c) a product card that has no photo yet
  await hold(cdp, await framePoint(page, "#nph"));
  const noPhoto = (await sheet(page).count()) ? await sheet(page).innerText() : "";
  rec("hold.product-without-photo", /افزودن عکس برای این کالا/.test(noPhoto), noPhoto.replace(/\s+/g, " ").slice(0, 110));
  beforeCount = S.images.length;
  await page.locator('input[type="file"]').setInputFiles({ name: "p.png", mimeType: "image/png", buffer: PNG });
  await sleep(1500);
  const sentLast = S.images[S.images.length - 1] || {};
  rec("image.product-card-hint-sent", S.images.length === beforeCount + 1 && sentLast.product === "/products/p1" && sentLast.src === "", JSON.stringify(sentLast).slice(0, 140));

  // 8) product photo through next/image
  await hold(cdp, await framePoint(page, "#prod"));
  const pSheet = (await sheet(page).count()) ? await sheet(page).innerText() : "";
  rec("hold.product-photo", /عکس از گوشی/.test(pSheet) && !/با هوش مصنوعی/.test(pSheet), pSheet.replace(/\s+/g, " ").slice(0, 100));
  await page.locator('input[type="file"]').setInputFiles({ name: "p.png", mimeType: "image/png", buffer: PNG });
  await sleep(1500);
  rec("image.product-src-sent", /_next\/image|a1\.jpg/.test(S.images[S.images.length - 1]?.src || ""), S.images[S.images.length - 1]?.src);

  // 9) برگشت takes edits back one by one
  const undoBefore = S.undo;
  await btn(page, "برگشت").click();
  await sleep(2200);
  rec("undo.one-step", S.undos === 1 && S.undo === undoBefore - 1, `undo depth ${undoBefore} -> ${S.undo}`);
  const titleBack = await shopFrame(page).evaluate(() => document.querySelector("#title")?.textContent || "");
  rec("undo.preview-still-alive", Boolean(shopFrame(page)) && titleBack.length > 0, titleBack);
  await shot(page, "06-after-undo");
  while (await enabled(page, "برگشت")) {
    await btn(page, "برگشت").click();
    await sleep(1800);
  }
  rec("undo.disabled-at-bottom", !(await enabled(page, "برگشت")) && !(await enabled(page, "بیلد")), `undo=${S.undo} pending=${S.pending}`);

  // 10) build: both buttons lock, then برگشت stays locked
  await hold(cdp, await framePoint(page, "#title"));
  await page.locator("#shop-sheet-command").fill("رنگ تیتر را گرم‌تر کن");
  await page.getByRole("button", { name: "بفرست" }).click();
  await sleep(1800);
  rec("build.ready-with-pending", await enabled(page, "بیلد"), `pending=${S.pending}`);
  await btn(page, "بیلد").click();
  await sleep(900);
  const building = { build: await enabled(page, "بیلد"), undo: await enabled(page, "برگشت"), label: await page.locator('[role="group"]').innerText() };
  await shot(page, "07-building");
  rec("build.sent-as-revise", S.builds.length === 1 && S.builds[0].rebuild === true && S.builds[0].reviseOnly === true, JSON.stringify(S.builds[0] || {}));
  rec("build.locks-both-buttons", !building.build && !building.undo && /در حال بیلد/.test(building.label), building.label.replace(/\s+/g, " "));
  const cover = await page.evaluate(() => ({ text: document.body.innerText.replace(/\s+/g, " "), bars: document.querySelectorAll('[role="progressbar"] > span').length }));
  rec("build.progress-cover-shows-the-steps", /در حال طراحی ظاهر/.test(cover.text) && /فهم نوع فروشگاه/.test(cover.text) && cover.bars === 4, `bars=${cover.bars}`);
  rec("build.cover-blocks-holding-the-half-built-site", (await sheet(page).count()) === 0, "no sheet while building");
  await sleep(7500);
  const done = { build: await enabled(page, "بیلد"), undo: await enabled(page, "برگشت") };
  rec("build.undo-disabled-after-build", !done.undo && !done.build && S.undo === 0, `build=${done.build} undo=${done.undo}`);
  await shot(page, "08-after-build");

  rec("page.console", errors.length === 0, errors.slice(0, 3).join(" | "));
  await ctx.close();

  // 11) desktop keeps the side editor and has no phone bar
  const desk = await boot(browser, { w: 1280, h: 800 });
  const d = await desk.page.evaluate(() => ({
    aside: Boolean(document.querySelector('aside[aria-label="ویرایش فروشگاه"]')),
    command: Boolean(document.querySelector("#shop-command")),
    group: Boolean(document.querySelector('[role="group"][aria-label="بیلد و برگشت"]')),
  }));
  await shot(desk.page, "09-desktop");
  rec("desktop.editor-kept", d.aside && d.command && !d.group, JSON.stringify(d));
  await desk.ctx.close();

  fs.writeFileSync(path.join(OUT, "findings.json"), JSON.stringify(findings, null, 1));
  await browser.close();
  const failed = findings.filter((f) => !f.ok);
  console.log(`\n${findings.length - failed.length}/${findings.length} ok`);
  process.exit(failed.length ? 1 : 0);
}

main().catch((e) => {
  console.error("FATAL", e);
  process.exit(1);
});
