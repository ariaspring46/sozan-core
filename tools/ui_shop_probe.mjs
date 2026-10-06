// Shop-page probe: drives the panel «فروشگاه» tab (a `next build` + `next start` copy) against an isolated API
// (SOZAN_EDGE_DRY=1, a COPY of the lab tenant, SITE_BUILDER_DIR read-only). Reads are real; every write to the
// shop (/shop/build, /shop/chat) is stubbed in the browser; PATCH /shop/domain is real (state of the copy only).
//   PANEL=http://127.0.0.1:3998 API=http://127.0.0.1:8014 TOKEN_FILE=~/shop-lab/token OUT=./shop-shots \
//   [ONLY=ready,states,editor,loadfail,preview,pick,stale,domain] node tools/ui_shop_probe.mjs
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const HOME = process.env.HOME;
const BASE = process.env.PANEL || "http://127.0.0.1:3998";
const API = process.env.API || "http://127.0.0.1:8014";
const TOKEN = fs.readFileSync((process.env.TOKEN_FILE || path.join(HOME, "shop-lab/token")).replace(/^~/, HOME), "utf8").trim();
const OUT = process.env.OUT || path.join(HOME, "shop-lab/shots");
const ONLY = (process.env.ONLY || "").split(",").filter(Boolean);
fs.mkdirSync(OUT, { recursive: true });
const findings = [];
const rec = (id, ok, detail) => {
  findings.push({ id, ok, detail });
  console.log(`${ok ? "OK  " : "FAIL"} ${id} ${detail ?? ""}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const want = (n) => !ONLY.length || ONLY.includes(n);
const isPathname = (url, p) => {
  try {
    return new URL(url).pathname === p;
  } catch {
    return false;
  }
};

async function realShop() {
  const res = await fetch(`${API}/shop`, { headers: { Authorization: `Bearer ${TOKEN}` } });
  return res.json();
}

async function open(browser, { w = 390, h = 844, dark = false, shopStub = null, waitMs = 6000, stubWrites = true, chatMode = "", failShopGet = "" } = {}) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: "fa-IR", colorScheme: dark ? "dark" : "light" });
  await ctx.addInitScript((t) => {
    localStorage.setItem("sozan_token", t);
    localStorage.setItem("sozan_onboarded", "1");
  }, TOKEN);
  const page = await ctx.newPage();
  const errors = [];
  const calls = { shopGet: 0, build: 0, chat: 0 };
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 180)));
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(m.text().slice(0, 180));
  });
  await page.route("**/*", async (route) => {
    const req = route.request();
    const url = req.url();
    if (url.startsWith(API) && isPathname(url, "/shop") && req.method() === "GET") {
      calls.shopGet += 1;
      if (failShopGet === "abort") return route.abort("failed");
      if (failShopGet === "502") return route.fulfill({ status: 502, contentType: "text/html", body: "<html>Bad Gateway</html>" });
      if (shopStub) {
        const real = await realShop();
        const body = typeof shopStub === "function" ? shopStub(real, calls.shopGet) : shopStub;
        return route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify(body) });
      }
    }
    if (stubWrites && url.startsWith(API) && req.method() === "POST" && isPathname(url, "/shop/chat") && chatMode) {
      calls.chat += 1;
      calls.lastChatAt = Date.now();
      if (chatMode === "abort") return route.abort("failed");
      if (chatMode === "502") return route.fulfill({ status: 502, contentType: "text/html", body: "<html>Bad Gateway</html>" });
      await sleep(1800);
      const real = await realShop();
      const text = JSON.parse(req.postData() || "{}").text || "";
      return route.fulfill({
        status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" },
        body: JSON.stringify({ ...real, shop: { ...real.shop, pendingBuild: 1 }, patched: true, preview: { colors: { primary: "#7A1F2B" } },
          messages: [...(real.messages || []), { id: "u1", role: "user", text }, { id: "a1", role: "assistant", text: "رنگ اصلی زرشکی شد. تغییر در کادر است؛ هر وقت آماده بودی دکمهٔ «بیلد» را بزن." }] }),
      });
    }
    if (stubWrites && url.startsWith(API) && req.method() === "POST" && isPathname(url, "/shop/build")) {
      calls.build += 1;
      return route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify({ result: { ok: true }, ...(await realShop()) }) });
    }
    return route.continue();
  });
  await page.goto(`${BASE}/shop`, { waitUntil: "domcontentloaded" });
  await sleep(waitMs);
  return { ctx, page, errors, calls };
}

const shot = (page, name) => page.screenshot({ path: path.join(OUT, name + ".png") });

async function metrics(page) {
  return page.evaluate(() => {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const frame = document.querySelector("iframe");
    const aside = document.querySelector('aside[aria-label="ویرایش فروشگاه"]');
    const small = [];
    for (const el of document.querySelectorAll("button, a[href], select, input, textarea, [role=button]")) {
      if (el.closest("iframe")) continue;
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0 || r.bottom < 0 || r.top > vh) continue;
      if (el.classList.contains("tap")) continue; // .tap gives a 44px hit area through ::after
      if (el.tagName === "A" && el.getAttribute("dir") === "ltr" && el.closest("p")) continue; // a link inside a sentence
      const cs = getComputedStyle(el);
      if (cs.visibility === "hidden" || cs.display === "none") continue;
      if (r.width < 40 || r.height < 40) small.push(`${(el.getAttribute("aria-label") || el.textContent || el.tagName).trim().slice(0, 18)} ${Math.round(r.width)}x${Math.round(r.height)}`);
    }
    return {
      vw, vh,
      overflow: document.documentElement.scrollWidth > vw + 1,
      frameH: frame ? Math.round(frame.getBoundingClientRect().height) : 0,
      frameW: frame ? Math.round(frame.getBoundingClientRect().width) : 0,
      asideH: aside ? Math.round(aside.getBoundingClientRect().height) : 0,
      text: document.body.innerText.replace(/\s+/g, " "),
      alerts: [...document.querySelectorAll('[role="alert"]')].map((e) => e.textContent.trim()),
      small,
    };
  });
}


async function main() {
  const browser = await chromium.launch();


  if (want("ready")) {
    for (const [w, h] of [[390, 844], [360, 640], [412, 915]]) {
      const { ctx, page, errors } = await open(browser, { w, h });
      await shot(page, `01-ready-${w}x${h}`);
      const m = await metrics(page);
      rec(`ready.${w}x${h}.no-overflow`, !m.overflow, `scrollWidth ok=${!m.overflow}`);
      rec(`ready.${w}x${h}.preview-share`, m.frameH / m.vh >= (h < 700 ? 0.35 : 0.4), `iframe ${m.frameW}x${m.frameH} of ${m.vh}px (${Math.round((100 * m.frameH) / m.vh)}%), editor ${m.asideH}px`);
      rec(`ready.${w}x${h}.no-internal-url`, !/127\.0\.0\.1|localhost/.test(m.text), "no 127.0.0.1 in the page text");
      rec(`ready.${w}x${h}.no-stale-step-label`, !/در حال روشن کردن سایت زنده/.test(m.text), "ready shop must not say it is still starting");
      rec(`ready.${w}x${h}.no-error`, m.alerts.length === 0, JSON.stringify(m.alerts));
      rec(`ready.${w}x${h}.tap-targets`, m.small.length === 0, m.small.slice(0, 6).join(" | "));
      rec(`ready.${w}x${h}.console`, errors.length === 0, errors.slice(0, 2).join(" | "));
      await ctx.close();
    }
    const { ctx, page } = await open(browser, { dark: true });
    await shot(page, "01-ready-dark");
    await ctx.close();
  }

  if (want("states")) {
    const cases = {
      empty: (real) => ({ shop: {}, scan: real.scan, build: null, messages: [] }),
      building: (real, n) => ({
        shop: { ...real.shop, status: "running", pendingBuild: 0 },
        scan: real.scan,
        messages: real.messages,
        build: { ...real.build, status: "running", step: "DESIGN_CLOUD", stepLabel: "در حال طراحی ظاهر و چیدن کالاها…", startedAt: new Date(Date.now() - 45000).toISOString(), elapsedSec: 45 + n, error: "",
          pipeline: [{ id: "archetype", label: "فهم نوع فروشگاه", state: "done" }, { id: "DESIGN_CLOUD", label: "طراحی ظاهر", state: "active" }, { id: "COPY_TEMPLATE", label: "ساخت صفحه‌ها", state: "wait" }, { id: "DOCKER", label: "روشن کردن سایت", state: "wait" }] },
      }),
      failed: (real) => ({
        shop: { ...real.shop, status: "failed", error: "ساخت کامل نشد" },
        scan: real.scan, messages: real.messages,
        build: { ...real.build, status: "failed", step: "DESIGN_CLOUD", stepLabel: "", error: "طراحی سایت کامل نشد. دوباره بساز.", errorClass: "design",
          pipeline: [{ id: "archetype", label: "فهم نوع فروشگاه", state: "done" }, { id: "DESIGN_CLOUD", label: "طراحی ظاهر", state: "fail" }, { id: "COPY_TEMPLATE", label: "ساخت صفحه‌ها", state: "wait" }, { id: "DOCKER", label: "روشن کردن سایت", state: "wait" }] },
      }),
      pending: (real) => ({ shop: { ...real.shop, pendingBuild: 3 }, scan: real.scan, build: real.build, messages: real.messages }),
      scanrun: (real) => ({ ...real, scan: { ...real.scan, status: "running", handles: ["my_shop_page"] } }),
      scanerr: (real) => ({ ...real, scan: { ...real.scan, status: "error", error: "پیج پیدا نشد یا خصوصی است.", imported: 4 } }),
      scanreview: (real) => ({ ...real, scan: { ...real.scan, status: "done", needsReview: true, imported: 12, noImage: 7 } }),
      priceblock: (real) => ({ ...real, shop: { ...real.shop, priceBlocked: true, hidePrices: false } }),
      longbrand: (real) => ({ ...real, shop: { ...real.shop, brand: "فروشگاه بسیار طولانی زیورآلات دست‌ساز نقره و فیروزه اصل نیشابور و مشهد و اصفهان" } }),
      latinbrand: (real) => ({ ...real, shop: { ...real.shop, brand: "Silver&Turquoise Handmade Jewelry Store Mashhad" } }),
      hideprices: (real) => ({ ...real, shop: { ...real.shop, hidePrices: true } }),
    };
    for (const [name, stub] of Object.entries(cases)) {
      const { ctx, page, errors, calls } = await open(browser, { shopStub: stub, waitMs: 5000 });
      await shot(page, `02-state-${name}`);
      const m = await metrics(page);
      rec(`state.${name}.no-overflow`, !m.overflow, "");
      rec(`state.${name}.console`, errors.length === 0, errors.slice(0, 2).join(" | "));
      rec(`state.${name}.text`, true, m.text.slice(0, 260));
      if (m.small.length) rec(`state.${name}.tap-targets`, false, m.small.slice(0, 5).join(" | "));
      if (name === "building") {
        const before = calls.shopGet;
        await sleep(6000);
        rec("state.building.polling-rate", calls.shopGet - before <= 6, `${calls.shopGet - before} GET /shop in 6s`);
      }
      await ctx.close();
    }
  }



  if (want("editor")) {
    for (const mode of ["ok", "502", "abort"]) {
      const { ctx, page, calls } = await open(browser, { chatMode: mode, waitMs: 4500, w: 1280, h: 800 });
      const input = page.locator("#shop-command");
      await input.click();
      const hiddenNav = await page.evaluate(() => getComputedStyle(document.querySelector("nav[aria-label]")).display);
      await input.fill("رنگ اصلی را زرشکی کن");
      const send = page.locator('form button[aria-label="بفرست"]');
      await send.click();
      await sleep(700);
      let lost = calls.chat === 0;
      if (lost) {
        await page.evaluate(() => document.querySelector("#shop-command").form.requestSubmit());
        await sleep(300);
      }
      const during = await page.evaluate(() => ({
        disabled: document.querySelector("#shop-command").disabled,
        active: document.activeElement?.tagName,
        status: document.querySelector('[role="status"]')?.textContent.trim().slice(0, 60),
      }));
      await sleep(mode === "ok" ? 2600 : 1200);
      const after = await page.evaluate(() => ({
        value: document.querySelector("#shop-command").value,
        active: document.activeElement?.tagName,
        alerts: [...document.querySelectorAll('[role="alert"]')].map((e) => e.textContent.trim()),
        status: document.querySelector('[role="status"]')?.textContent.trim().slice(0, 120),
        pendingBanner: /تغییر در پیش‌نمایش است/.test(document.body.innerText),
        navShown: getComputedStyle(document.querySelector("nav[aria-label]")).display,
      }));
      await shot(page, `03-editor-${mode}`);
      if (mode === "ok") {
        rec("editor.send-tap-reaches-server-first-time", !lost, lost ? "the first tap on send was lost (button moved between mousedown and mouseup)" : "ok");
        rec("editor.input-stays-enabled-while-waiting", !during.disabled, `disabled=${during.disabled} focus=${during.active}`);
        rec("editor.focus-after-reply", after.active === "INPUT", `focus=${after.active}`);
        rec("editor.draft-cleared-after-success", after.value === "", `"${after.value}"`);
        rec("editor.pending-banner-after-edit", after.pendingBanner, "«n تغییر در پیش‌نمایش است»");
        rec("editor.reply-shown", /زرشکی/.test(after.status || ""), after.status);
      } else {
        rec(`editor.${mode}.draft-kept`, after.value === "رنگ اصلی را زرشکی کن", `"${after.value}"`);
        rec(`editor.${mode}.error-persian`, after.alerts.length > 0 && !/[A-Za-z]{4,}/.test(after.alerts.join(" ")), JSON.stringify(after.alerts));
      }
      await ctx.close();
    }
  }

  if (want("loadfail")) {
    for (const mode of ["abort", "502"]) {
      const { ctx, page } = await open(browser, { failShopGet: mode, waitMs: 4000 });
      await shot(page, `04-loadfail-${mode}`);
      const m = await metrics(page);
      rec(`loadfail.${mode}.does-not-claim-no-shop`, !/هنوز سایت فروشگاه ساخته نشده/.test(m.text), "a failed load must not say the shop does not exist");
      rec(`loadfail.${mode}.error-persian`, m.alerts.length > 0 && !/[A-Za-z]{4,}/.test(m.alerts.join(" ")), JSON.stringify(m.alerts));
      rec(`loadfail.${mode}.retry-offered`, /دوباره|تلاش/.test(m.text), m.text.slice(0, 160));
      await ctx.close();
    }
  }

  // The editor, the page chips and the design/browse toggle exist on desktop only; on a phone the tab is just the
  // preview (tools/ui_shop_mobile_probe.mjs covers it).
  if (want("preview")) {
    const { ctx, page } = await open(browser, { waitMs: 7000, w: 1280, h: 800 });
    const src0 = await page.locator("iframe").getAttribute("src");
    await page.getByRole("button", { name: "کالاها", exact: true }).click();
    await sleep(1500);
    const src1 = await page.locator("iframe").getAttribute("src");
    rec("preview.page-chip-changes-the-frame", src1 !== src0 && /\/products/.test(src1 || ""), `${src0?.slice(-40)} → ${src1?.slice(-40)}`);
    await shot(page, "05-preview-products");
    await page.getByRole("button", { name: "طراحی", exact: true }).click();
    await sleep(800);
    const src2 = await page.locator("iframe").getAttribute("src");
    rec("preview.mode-toggle-switches-to-browse", /sozan=browse/.test(src2 || ""), src2?.slice(-60));
    await page.getByRole("button", { name: "تازه‌کردن" }).click();
    await sleep(600);
    const link = await page.locator('a[aria-label="باز کردن ویترین در تب جدید"]').getAttribute("href");
    rec("preview.external-link", /^https:\/\/azmaish-panl\.sozan-core\.ir\/products/.test(link || ""), link);
    await page.getByRole("button", { name: "بستن پیش‌نمایش" }).click();
    await sleep(500);
    await shot(page, "05-preview-closed");
    const reopened = await page.getByRole("button", { name: "باز کردن", exact: true }).count();
    rec("preview.close-offers-reopen", reopened > 0, `reopen buttons=${reopened}`);
    await page.getByRole("button", { name: "باز کردن", exact: true }).click();
    await sleep(800);
    rec("preview.reopen-restores-frame", (await page.locator("iframe").count()) === 1, "iframe back");
    await ctx.close();
  }

  if (want("pick")) {
    const { ctx, page } = await open(browser, { waitMs: 9000, w: 1280, h: 800 });
    const frame = page.frameLocator("iframe");
    try {
      await frame.locator("h1, h2").first().click({ timeout: 8000 });
      await sleep(1200);
      const sel = await page.evaluate(() => ({ section: !!document.querySelector('section[aria-label="بخش انتخاب‌شده"]'), text: document.querySelector('section[aria-label="بخش انتخاب‌شده"]')?.textContent.slice(0, 80) }));
      await shot(page, "06-pick");
      rec("pick.tapping-a-heading-selects-it", sel.section, sel.text || "no selection panel");
    } catch (e) {
      rec("pick.tapping-a-heading-selects-it", false, String(e).slice(0, 120));
    }
    await ctx.close();
  }

  if (want("stale")) {
    const { ctx, page } = await open(browser, { waitMs: 500 });
    await ctx.close();
    const ctx2 = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: "fa-IR" });
    await ctx2.addInitScript((t) => { localStorage.setItem("sozan_token", t); localStorage.setItem("sozan_onboarded", "1"); }, TOKEN);
    const p2 = await ctx2.newPage();
    await p2.route(/azmaish-panl\.sozan-core\.ir/, (route) => route.abort("failed"));
    await p2.goto(`${BASE}/shop`, { waitUntil: "domcontentloaded" });
    await sleep(11000);
    await shot(p2, "07-frame-blocked");
    const txt = await p2.evaluate(() => document.body.innerText.replace(/\s+/g, " "));
    rec("stale.frame-failure-is-explained", /پیش‌نمایش بار نشد/.test(txt), txt.slice(0, 140));
    await ctx2.close();
  }

  if (want("domain")) {

  const attempts = [
    ["invalid", "bad domain with spaces"],
    ["taken", "taken.example.com"],
    ["zone", "app.sozan-core.ir"],
    ["custom", "shop.example.com"],
    ["url-paste", "https://Shop.Example.com/path?x=1"],
    ["idn", "فروشگاه.ir"],
  ];
  for (const [name, value] of attempts) {
    const { ctx, page, errors } = await open(browser, { waitMs: 4500 });
    await page.getByRole("button", { name: /دامنه و انتشار/ }).click();
    await sleep(600);
    if (name === "invalid") await shot(page, "09-domain-sheet");
    const input = page.locator("#shop-domain");
    const attrs = await input.evaluate((el) => ({ cap: el.getAttribute("autocapitalize"), corr: el.getAttribute("autocorrect"), mode: el.getAttribute("inputmode") }));
    if (name === "invalid") rec("domain.input-is-url-friendly", attrs.cap === "none" && attrs.corr === "off" && attrs.mode === "url", JSON.stringify(attrs));
    await input.fill(value);
    await page.getByRole("button", { name: "ذخیره دامنه" }).click();
    await sleep(2500);
    const st = await page.evaluate(() => ({
      dialog: !!document.querySelector('[role="dialog"]'),
      alerts: [...document.querySelectorAll('[role="alert"]')].map((e) => e.textContent.trim()),
      text: (document.querySelector('[role="dialog"]')?.innerText || "").replace(/\s+/g, " ").slice(0, 400),
      value: document.querySelector("#shop-domain")?.value,
    }));
    await shot(page, `09-domain-${name}`);
    if (name === "invalid" || name === "taken" || name === "zone") {
      rec(`domain.${name}.error-is-shown-in-the-sheet`, st.dialog && st.alerts.length > 0, `dialog=${st.dialog} alerts=${JSON.stringify(st.alerts)}`);
      rec(`domain.${name}.no-unhandled-rejection`, errors.length === 0, errors.slice(0, 2).join(" | "));
    } else {
      rec(`domain.${name}.shows-dns-instructions`, st.dialog && /CNAME/.test(st.text), st.text.slice(0, 200));
      rec(`domain.${name}.no-unhandled-rejection`, errors.length === 0, errors.slice(0, 2).join(" | "));
    }
    await ctx.close();
  }
    await fetch(`${API}/shop/domain`, { method: "PATCH", headers: { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" }, body: JSON.stringify({ domain: "" }) });
  }

  fs.writeFileSync(path.join(OUT, "findings.json"), JSON.stringify(findings, null, 1));
  await browser.close();
}

main().catch((e) => {
  console.error("FATAL", e);
  process.exit(1);
});
