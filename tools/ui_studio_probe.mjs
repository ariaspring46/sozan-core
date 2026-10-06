// Studio probe: the «استودیو» tab (library), the campaign list and a campaign page, on a `next build` copy
// against an isolated API (a COPY of the lab tenant; media and campaigns are read from the real store, read-only).
// Every write (PATCH /campaigns/<id>, POST /campaigns/<id>/compose, /studio/*) is stubbed in the browser.
//   PANEL=http://127.0.0.1:3998 API=http://127.0.0.1:8014 TOKEN_FILE=~/shop-lab/token OUT=./studio-shots \
//   [ONLY=library,states,campaigns,detail] node tools/ui_studio_probe.mjs
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const HOME = process.env.HOME;
const BASE = process.env.PANEL || "http://127.0.0.1:3998";
const API = process.env.API || "http://127.0.0.1:8014";
const TOKEN = fs.readFileSync((process.env.TOKEN_FILE || path.join(HOME, "shop-lab/token")).replace(/^~/, HOME), "utf8").trim();
const OUT = process.env.OUT || path.join(HOME, "shop-lab/studio-shots");
const ONLY = (process.env.ONLY || "").split(",").filter(Boolean);
fs.mkdirSync(OUT, { recursive: true });
const findings = [];
const rec = (id, ok, detail) => {
  findings.push({ id, ok, detail });
  console.log(`${ok ? "OK  " : "FAIL"} ${id} ${detail ?? ""}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const want = (n) => !ONLY.length || ONLY.includes(n);
const pathOf = (url) => {
  try {
    return new URL(url).pathname;
  } catch {
    return "";
  }
};
const json = (body, status = 200) => ({ status, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify(body) });
async function realContent() {
  const res = await fetch(`${API}/studio/content`, { headers: { Authorization: `Bearer ${TOKEN}` } });
  return res.json();
}

async function open(browser, { path: pagePath = "/studio", w = 390, h = 844, dark = false, content = null, contentStatus = 200, stubWrites = true, settle = 7000 } = {}) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: "fa-IR", colorScheme: dark ? "dark" : "light" });
  await ctx.addInitScript((t) => {
    localStorage.setItem("sozan_token", t);
    localStorage.setItem("sozan_onboarded", "1");
  }, TOKEN);
  const page = await ctx.newPage();
  const stats = { media: 0, bytes: 0, requests: [], writes: [], errors: [] };
  page.on("pageerror", (e) => stats.errors.push(String(e).slice(0, 160)));
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource/.test(m.text())) stats.errors.push(m.text().slice(0, 160));
  });
  page.on("response", async (res) => {
    const url = res.url();
    if (url.startsWith(API) && /\/campaigns\/[^/]+\/file\//.test(url)) {
      stats.media += 1;
      stats.bytes += Number(res.headers()["content-length"] || 0);
    }
  });
  await page.route("**/*", async (route) => {
    const req = route.request();
    const url = req.url();
    if (url.startsWith(API)) {
      const p = pathOf(url);
      if (req.method() === "GET" && p === "/studio/content" && (content || contentStatus !== 200)) {
        if (contentStatus !== 200) return route.fulfill({ status: contentStatus, contentType: "text/html", body: "<html>Bad Gateway</html>" });
        return route.fulfill(json(typeof content === "function" ? content(await realContent()) : content));
      }
      if (stubWrites && req.method() !== "GET" && req.method() !== "OPTIONS") {
        stats.writes.push(`${req.method()} ${p}`);
        await sleep(1200);
        const m = p.match(/^\/campaigns\/([^/]+)(\/compose)?$/);
        if (m) {
          // the real campaign comes back, with the edited fields merged in, as the API does
          const real = await (await fetch(`${API}/campaigns/${m[1]}`, { headers: { Authorization: `Bearer ${TOKEN}` } })).json();
          let body = {};
          try {
            body = JSON.parse(req.postData() || "{}");
          } catch {
            /* none */
          }
          return route.fulfill(json({ ...real, title: body.title ?? real.title, subtitle: body.subtitle ?? real.subtitle, cta: body.cta ?? real.cta }));
        }
        return route.fulfill(json({ ok: true }));
      }
    }
    return route.continue();
  });
  await page.goto(`${BASE}${pagePath}`, { waitUntil: "domcontentloaded" });
  await sleep(settle);
  return { ctx, page, stats };
}

const shot = (page, name, full = false) => page.screenshot({ path: path.join(OUT, name + ".png"), fullPage: full });
async function layout(page) {
  return page.evaluate(() => {
    const small = [];
    for (const el of document.querySelectorAll("button, a[href], summary, select, input, textarea")) {
      if (el.classList.contains("tap")) continue;
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility === "hidden" || cs.display === "none") continue;
      if (r.height < 43.5 || r.width < 43.5) small.push(`${(el.getAttribute("aria-label") || el.textContent || el.tagName).trim().slice(0, 16)} ${Math.round(r.width)}x${Math.round(r.height)}`);
    }
    const scroller = [...document.querySelectorAll("*")].filter((e) => e.scrollHeight > e.clientHeight + 40 && getComputedStyle(e).overflowY !== "visible").sort((a, b) => b.scrollHeight - a.scrollHeight)[0];
    return {
      overflowX: document.documentElement.scrollWidth > innerWidth + 1,
      imgs: document.images.length,
      videos: document.querySelectorAll("video").length,
      scrollH: scroller ? scroller.scrollHeight : 0,
      small: [...new Set(small)].slice(0, 8),
      text: document.body.innerText.replace(/\s+/g, " ").slice(0, 900),
    };
  });
}

async function main() {
  const browser = await chromium.launch();

  if (want("library")) {
    const { ctx, page, stats } = await open(browser, { settle: 9000 });
    const m = await layout(page);
    await shot(page, "01-library-top");
    rec("library.loads-little-media-up-front", stats.bytes < 12 * 1024 * 1024, `${stats.media} media requests, ${(stats.bytes / 1048576).toFixed(1)} MB fetched on open (first screen shows ${Math.min(m.imgs, 3)} pictures)`);
    rec("library.media-count-is-proportional", stats.media <= 14, `${stats.media} files for the shelf`);
    rec("library.no-overflow", !m.overflowX, "");
    rec("library.tap-targets", m.small.length === 0, m.small.join(" | "));
    rec("library.shelf-height", m.scrollH < 9000, `scroll height ${m.scrollH}px (${m.imgs} images, ${m.videos} videos in the DOM)`);
    const text = m.text;
    rec("library.has-date-or-format-label", /مهر|پست|استوری/.test(text), text.slice(0, 160));
    rec("library.has-caption-or-copy", /کپشن|کپی/.test(text), "a card should offer the caption");
    rec("library.has-download-or-edit", /دانلود|ویرایش/.test(text), "a card should offer download / edit");
    // scroll to the middle and look again
    await page.evaluate(() => {
      const sc = [...document.querySelectorAll("*")].filter((e) => e.scrollHeight > e.clientHeight + 40 && getComputedStyle(e).overflowY !== "visible").sort((a, b) => b.scrollHeight - a.scrollHeight)[0];
      if (sc) sc.scrollTop = 1800;
    });
    await sleep(1500);
    await shot(page, "01-library-mid");
    rec("library.console", stats.errors.length === 0, stats.errors.slice(0, 2).join(" | "));
    await ctx.close();
    const dark = await open(browser, { dark: true, settle: 6000 });
    await shot(dark.page, "01-library-dark");
    await dark.ctx.close();
  }

  if (want("states")) {
    const states = {
      empty: () => ({ items: [], drafts: [] }),
      error502: null,
      running: (real) => ({ items: [{ id: "run-1", title: "پست یلدا برای انگشتر نقره", copies: [], assets: [], compose: "running", composeStage: "photo", startedAt: Date.now() / 1000 - 38 }, ...real.items.slice(2, 3)], drafts: [] }),
      failed: (real) => ({ items: real.items.filter((i) => i.compose === "failed").slice(0, 2), drafts: [] }),
      longtitle: (real) => ({ items: real.items.slice(2, 3).map((i) => ({ ...i, title: "پست بسیار بلند برای مجموعهٔ زیورآلات دست‌ساز نقره و فیروزهٔ نیشابور و مشهد و اصفهان با تخفیف ویژهٔ یلدا" })), drafts: [] }),
    };
    for (const [name, content] of Object.entries(states)) {
      const { ctx, page, stats } = await open(browser, name === "error502" ? { contentStatus: 502, settle: 3500 } : { content, settle: 4500 });
      const m = await layout(page);
      await shot(page, `02-state-${name}`);
      rec(`state.${name}.no-overflow`, !m.overflowX, "");
      rec(`state.${name}.text`, true, m.text.slice(0, 220));
      if (name === "error502") rec("state.error502.persian-and-retry", /سرور/.test(m.text) && /دوباره|تازه/.test(m.text), m.text.slice(0, 160));
      if (name === "failed") rec("state.failed.explains-what-to-do", /چت|دوباره/.test(m.text), m.text.slice(0, 160));
      if (name === "running") rec("state.running.shows-progress", /ثانیه|ساخت/.test(m.text), "");
      rec(`state.${name}.console`, stats.errors.length === 0, stats.errors.slice(0, 2).join(" | "));
      await ctx.close();
    }
  }

  if (want("campaigns")) {
    const { ctx, page, stats } = await open(browser, { path: "/campaigns", settle: 4000 });
    const m = await layout(page);
    await shot(page, "03-campaign-list");
    rec("campaigns.list-no-overflow", !m.overflowX, "");
    rec("campaigns.list-tap-targets", m.small.length === 0, m.small.join(" | "));
    rec("campaigns.list-distinguishes-items", /مهر|پست|استوری|وضعیت/.test(m.text), m.text.slice(0, 200));
    rec("campaigns.console", stats.errors.length === 0, stats.errors.slice(0, 2).join(" | "));
    await ctx.close();
  }

  if (want("detail")) {
    const content = await realContent();
    const ready = content.items.find((i) => i.compose === "ready" && i.assets.some((a) => a.kind === "video"));
    const { ctx, page, stats } = await open(browser, { path: `/campaigns/${ready.id}`, settle: 9000 });
    const m = await layout(page);
    await shot(page, "04-campaign-detail");
    rec("detail.loads-little-media-up-front", stats.bytes < 6 * 1024 * 1024, `${stats.media} media, ${(stats.bytes / 1048576).toFixed(1)} MB on open`);
    rec("detail.no-overflow", !m.overflowX, "");
    rec("detail.tap-targets", m.small.length === 0, m.small.join(" | "));
    // save feedback: edit the title and press «ذخیره متن»
    const titleInput = page.locator("input").first();
    await titleInput.click();
    await titleInput.fill("عنوان تازه برای آزمون");
    let posted = false;
    page.on("request", (r) => {
      if (r.method() === "PATCH") posted = true;
    });
    await page.getByRole("button", { name: "ذخیره متن" }).click();
    await sleep(500);
    if (!posted) {
      rec("detail.first-tap-on-save-works", false, "the first tap on «ذخیره متن» was lost");
      await page.evaluate(() => [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "ذخیره متن").click());
    } else rec("detail.first-tap-on-save-works", true, "");
    await sleep(2200);
    const after = await page.evaluate(() => document.body.innerText.replace(/\s+/g, " "));
    await shot(page, "04-campaign-saved");
    rec("detail.save-says-saved", /ذخیره شد/.test(after), after.slice(0, 120));
    rec("detail.console", stats.errors.length === 0, stats.errors.slice(0, 2).join(" | "));
    await ctx.close();
  }

  fs.writeFileSync(path.join(OUT, "findings.json"), JSON.stringify(findings, null, 1));
  await browser.close();
}

main().catch((e) => {
  console.error("FATAL", e);
  process.exit(1);
});
