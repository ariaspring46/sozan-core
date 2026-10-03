// App-menu probe: on a phone the app has no bottom tab bar, the header carries a hamburger that opens a drawer with every
// destination; on desktop the fixed sidebar stays. Reads are real (isolated API), nothing is written.
//   PANEL=http://127.0.0.1:3998 API=http://127.0.0.1:8014 TOKEN_FILE=~/shop-lab/token OUT=./menu-shots node tools/ui_menu_probe.mjs
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const HOME = process.env.HOME;
const BASE = process.env.PANEL || "http://127.0.0.1:3998";
const API = process.env.API || "http://127.0.0.1:8014";
const TOKEN = fs.readFileSync((process.env.TOKEN_FILE || path.join(HOME, "shop-lab/token")).replace(/^~/, HOME), "utf8").trim();
const OUT = process.env.OUT || path.join(HOME, "shop-lab/menu-shots");
fs.mkdirSync(OUT, { recursive: true });
const findings = [];
const rec = (id, ok, detail) => {
  findings.push({ id, ok, detail });
  console.log(`${ok ? "OK  " : "FAIL"} ${id} ${detail ?? ""}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const DESTINATIONS = ["چت", "فروشگاه", "استودیو", "صندوق", "فروش", "بیشتر"];

async function open(browser, route, { w = 390, h = 844, dark = false, unread = 0 } = {}) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 2, isMobile: w < 800, hasTouch: w < 800, locale: "fa-IR", colorScheme: dark ? "dark" : "light" });
  await ctx.addInitScript((t) => {
    localStorage.setItem("sozan_token", t);
    localStorage.setItem("sozan_onboarded", "1");
  }, TOKEN);
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource|ERR_/.test(m.text())) errors.push(m.text().slice(0, 160));
  });
  await page.route(`${API}/inbox/unread`, (route) => route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify({ count: unread }) }));
  await page.goto(`${BASE}${route}`, { waitUntil: "domcontentloaded" });
  await sleep(4500);
  return { ctx, page, errors };
}
const shot = (page, name) => page.screenshot({ path: path.join(OUT, `${name}.png`) });
const menuBtn = (page) => page.getByRole("button", { name: /^منو/ });
const drawer = (page) => page.getByRole("dialog", { name: "منوی سوزان" });

async function main() {
  const browser = await chromium.launch();

  for (const [w, h] of [[360, 640], [390, 844], [412, 915]]) {
    for (const route of ["/chat", "/shop", "/sales"]) {
      const { ctx, page, errors } = await open(browser, route, { w, h, unread: 3 });
      const m = await page.evaluate(() => {
        const vw = innerWidth;
        const btn = [...document.querySelectorAll("button")].find((b) => /^منو/.test(b.getAttribute("aria-label") || ""));
        const r = btn?.getBoundingClientRect();
        const navs = [...document.querySelectorAll("nav")].filter((n) => getComputedStyle(n).display !== "none");
        const header = document.querySelector("header")?.getBoundingClientRect();
        return {
          overflow: document.documentElement.scrollWidth > vw + 1,
          btn: r ? { w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top), right: Math.round(vw - r.right) } : null,
          visibleNavs: navs.length,
          headerH: Math.round(header?.height || 0),
          label: btn?.getAttribute("aria-label"),
        };
      });
      rec(`${route}.${w}.no-bottom-bar`, m.visibleNavs === 0, `visible <nav>=${m.visibleNavs}`);
      rec(`${route}.${w}.hamburger`, Boolean(m.btn) && m.btn.w >= 44 && m.btn.h >= 44, JSON.stringify(m.btn));
      rec(`${route}.${w}.no-overflow`, !m.overflow, "");
      rec(`${route}.${w}.unread-in-label`, /3/.test(m.label || "") || /۳/.test(m.label || ""), m.label);
      rec(`${route}.${w}.console`, errors.length === 0, errors.slice(0, 2).join(" | "));
      if (w === 390) await shot(page, `01-${route.slice(1)}-closed`);
      await ctx.close();
    }
  }

  // open / use / close on the phone
  {
    const { ctx, page } = await open(browser, "/chat", { unread: 3 });
    await menuBtn(page).click();
    await sleep(400);
    await shot(page, "02-chat-open");
    rec("menu.opens", (await drawer(page).count()) === 1, "dialog is there");
    const links = await drawer(page).evaluate((el) => [...el.querySelectorAll("a")].map((a) => ({ text: a.textContent.trim().replace(/\s+/g, " "), h: Math.round(a.getBoundingClientRect().height), href: a.getAttribute("href") })));
    const shown = links.map((l) => l.text.replace(/^[\d۰-۹+]+|[\d۰-۹+]+$/g, "").trim());
    rec("menu.every-destination", DESTINATIONS.every((d) => shown.some((t) => t.startsWith(d))), links.map((l) => l.text).join(" | "));
    rec("menu.tap-targets", links.every((l) => l.h >= 44), links.map((l) => l.h).join(","));
    rec("menu.unread-badge", links.some((l) => /صندوق/.test(l.text) && /[3۳]/.test(l.text)), "inbox row shows 3");
    rec("menu.current-page-marked", (await drawer(page).locator('a[aria-current="page"]').count()) === 1, "exactly one current page");
    rec("menu.focus-inside", await page.evaluate(() => !!document.activeElement?.closest("#app-menu")), "focus moved into the menu");
    await page.keyboard.press("Escape");
    await sleep(300);
    rec("menu.escape-closes", (await drawer(page).count()) === 0, "Escape closes it");
    rec("menu.focus-returns", await page.evaluate(() => /^منو/.test(document.activeElement?.getAttribute("aria-label") || "")), "focus is back on the hamburger");
    await menuBtn(page).click();
    await sleep(300);
    const sheet = await drawer(page).boundingBox();
    await page.mouse.click(30, 400); // the scrim is on the other side of the drawer (RTL: drawer on the right)
    await sleep(300);
    rec("menu.scrim-closes", (await drawer(page).count()) === 0 && sheet.x > 60, `drawer x=${Math.round(sheet.x)}`);
    await menuBtn(page).click();
    await sleep(300);
    await drawer(page).getByRole("link", { name: /^فروشگاه/ }).click();
    await page.waitForURL(/\/shop/, { timeout: 8000 });
    await sleep(800);
    rec("menu.navigates-and-closes", (await drawer(page).count()) === 0 && /\/shop/.test(page.url()), page.url());
    await menuBtn(page).click();
    await sleep(300);
    await drawer(page).getByRole("link", { name: /^فروشگاه/ }).click();
    await sleep(400);
    rec("menu.same-page-link-closes", (await drawer(page).count()) === 0, "tapping the current page closes the menu");
    await menuBtn(page).click();
    await sleep(300);
    await drawer(page).getByRole("radio", { name: "تیره" }).click();
    await sleep(400);
    rec("menu.theme-toggle-works", (await page.evaluate(() => document.documentElement.getAttribute("data-theme") || document.documentElement.className)).includes("dark"), "dark theme chosen from the menu");
    await shot(page, "03-menu-dark");
    await drawer(page).getByRole("radio", { name: "خودکار" }).click();
    await ctx.close();
  }

  // the phone keyboard no longer has a tab bar to hide: a long field page keeps its field in view
  {
    const { ctx, page } = await open(browser, "/chat", { w: 390, h: 844 });
    const input = page.locator("textarea").first();
    await input.click();
    await page.setViewportSize({ width: 390, height: 480 });
    await sleep(800);
    const k = await page.evaluate(() => {
      const t = document.querySelector("textarea")?.getBoundingClientRect();
      return { vh: innerHeight, bottom: Math.round(t?.bottom || 0) };
    });
    rec("keyboard.composer-visible", k.bottom <= k.vh, JSON.stringify(k));
    await shot(page, "04-keyboard");
    await ctx.close();
  }

  // dark and desktop
  {
    const { ctx, page } = await open(browser, "/sales", { dark: true });
    await menuBtn(page).click();
    await sleep(300);
    await shot(page, "05-dark-open");
    await ctx.close();
    const desk = await open(browser, "/chat", { w: 1280, h: 800 });
    const d = await desk.page.evaluate(() => ({
      hamburger: [...document.querySelectorAll("button")].some((b) => /^منو/.test(b.getAttribute("aria-label") || "") && getComputedStyle(b).display !== "none"),
      sidebar: [...document.querySelectorAll("nav")].some((n) => getComputedStyle(n).display !== "none" && n.getBoundingClientRect().width > 150),
    }));
    await shot(desk.page, "06-desktop");
    rec("desktop.sidebar-kept-no-hamburger", d.sidebar && !d.hamburger, JSON.stringify(d));
    await desk.ctx.close();
  }

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
