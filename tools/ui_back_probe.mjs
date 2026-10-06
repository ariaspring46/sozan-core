// Phone "back" button probe: the menu, sheets and editors close on back, back from a page opened from the menu returns
// in one press, and on Android the first panel page asks for a second press before leaving. Also checks the viewport meta
// lets the Android keyboard shrink the page, and that a signed-in seller stays signed in (login page skips ahead, an old
// token is renewed). Everything the page reads from the API is stubbed; nothing is written.
//   PANEL=http://127.0.0.1:3998 API=http://127.0.0.1:8014 TOKEN_FILE=~/chat-lab/token node tools/ui_back_probe.mjs
import { chromium, devices } from "playwright";
import fs from "node:fs";
import path from "node:path";

const HOME = process.env.HOME;
const BASE = process.env.PANEL || "http://127.0.0.1:3998";
const API = process.env.API || "http://127.0.0.1:8014";
const TOKEN = fs.readFileSync((process.env.TOKEN_FILE || path.join(HOME, "chat-lab/token")).replace(/^~/, HOME), "utf8").trim();
const EXIT_HINT = "برای خروج، دوباره «برگشت» را بزن";
const now = Math.floor(Date.now() / 1000);
const findings = [];
const rec = (id, ok, detail) => {
  findings.push({ id, ok, detail });
  console.log(`${ok ? "OK  " : "FAIL"} ${id} ${detail ?? ""}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const json = (body) => ({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify(body) });

const MESSAGES = [
  { id: "1", role: "user", text: "سلام", at: now - 60 },
  { id: "2", role: "assistant", text: "سلام! بگو چه کاری برایت بکنم.", at: now - 50 },
];

const b64 = (value) => Buffer.from(JSON.stringify(value)).toString("base64url");
/** توکن ساختگی با iat/exp دلخواه (امضا مهم نیست؛ API ساختگی است). */
const fakeJwt = (iat, exp) => `${b64({ alg: "HS256" })}.${b64({ sub: "u", iat, exp })}.sig`;

async function open(browser, device, start, { token = TOKEN, onboarded = true } = {}) {
  const ctx = await browser.newContext({ ...devices[device], locale: "fa-IR" });
  await ctx.addInitScript(
    ([t, o]) => {
      if (location.protocol === "about:" || sessionStorage.getItem("probe-seeded")) return;
      sessionStorage.setItem("probe-seeded", "1");
      localStorage.setItem("sozan_token", t);
      if (o) localStorage.setItem("sozan_onboarded", "1");
    },
    [token, onboarded],
  );
  const page = await ctx.newPage();
  const errors = [];
  const refreshes = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
  await page.route(`${API}/**`, async (route) => {
    const p = new URL(route.request().url()).pathname;
    if (p === "/auth/me") return route.fulfill(json({ id: "u", phone: "09111234567", role: "admin", onboarded: true, isAdmin: false }));
    if (p === "/auth/refresh") {
      refreshes.push(route.request().headers().authorization || "");
      return route.fulfill(json({ access_token: fakeJwt(now, now + 60 * 86400), token_type: "bearer" }));
    }
    if (p === "/onboard") return route.fulfill(json({ profile: { onboarded: true } }));
    if (p === "/chat") return route.fulfill(json({ messages: MESSAGES, pendingConfirm: null, brand: "نقره‌خانه", threadId: "t1", threads: [{ id: "t1", title: "گفتگو" }, { id: "t2", title: "پست یلدا" }] }));
    if (p === "/catalog") return route.fulfill(json({ products: [], categories: [] }));
    if (p === "/inbox/unread") return route.fulfill(json({ count: 0 }));
    return route.fulfill(json({}));
  });
  await page.goto("about:blank");
  await page.goto(`${BASE}${start}`, { waitUntil: "domcontentloaded" });
  await sleep(3500);
  return { ctx, page, errors, refreshes };
}

const at = (page) => page.evaluate(() => ({ path: location.href.startsWith("about:") ? "about:blank" : location.pathname, len: history.length, index: window.navigation?.currentEntry?.index ?? null }));

async function back(page) {
  await page.goBack({ waitUntil: "commit", timeout: 5000 }).catch(() => null);
  await sleep(700);
  return at(page);
}

const menuOpen = (page) => page.locator("#app-menu").isVisible().catch(() => false);
const hintShown = (page) => page.getByText(EXIT_HINT).isVisible().catch(() => false);
const firstTap = (page) => page.getByRole("log").first().tap({ position: { x: 40, y: 40 } }).catch(() => page.mouse.click(40, 300));

async function android(browser) {
  const D = "Pixel 7";

  // 1. Menu: back closes it; closing with X leaves no dead back press; back at the first page asks once, then leaves.
  {
    const { ctx, page, errors } = await open(browser, D, "/chat");
    const meta = await page.locator('meta[name="viewport"]').getAttribute("content");
    rec("viewport.keyboard-resizes-page", /interactive-widget=resizes-content/.test(meta || ""), meta);
    const before = await at(page);
    await firstTap(page);
    await sleep(300);
    const armed = await at(page);
    rec("guard.armed-after-first-touch", armed.len === before.len + 1, `history ${before.len} → ${armed.len}`);
    await page.getByRole("button", { name: "منو", exact: true }).tap();
    await sleep(500);
    rec("menu.opens", await menuOpen(page));
    let where = await back(page);
    rec("menu.back-closes-menu", !(await menuOpen(page)) && where.path === "/chat", JSON.stringify(where));
    await page.getByRole("button", { name: "منو", exact: true }).tap();
    await sleep(500);
    await page.locator("#app-menu").getByRole("button", { name: "بستن منو" }).tap();
    await sleep(600);
    where = await back(page);
    rec("menu.closed-by-x-then-back-asks-to-exit", (await hintShown(page)) && where.path === "/chat", JSON.stringify(where));
    where = await back(page);
    rec("guard.second-back-leaves", where.path === "about:blank", JSON.stringify(where));
    rec("errors.menu", errors.length === 0, errors.join(" | "));
    await ctx.close();
  }

  // 2. A page opened from the menu: one back returns to chat; the hint re-arms after it fades.
  {
    const { ctx, page, errors } = await open(browser, D, "/chat");
    await firstTap(page);
    await page.getByRole("button", { name: "منو", exact: true }).tap();
    await sleep(500);
    await page.locator("#app-menu").getByRole("link", { name: "فروشگاه" }).tap();
    await page.waitForURL(/\/shop/, { timeout: 8000 }).catch(() => null);
    await sleep(1500);
    rec("nav.menu-link-opens-page", (await at(page)).path === "/shop");
    let where = await back(page);
    rec("nav.one-back-returns-to-chat", where.path === "/chat" && !(await menuOpen(page)), JSON.stringify(where));
    where = await back(page);
    rec("nav.then-back-asks-to-exit", (await hintShown(page)) && where.path === "/chat", JSON.stringify(where));
    await sleep(3200);
    rec("guard.hint-fades", !(await hintShown(page)));
    where = await back(page);
    rec("guard.rearms-after-hint", (await hintShown(page)) && where.path === "/chat", JSON.stringify(where));
    rec("errors.nav", errors.length === 0, errors.join(" | "));
    await ctx.close();
  }

  // 3. Conversations sheet in the chat header.
  {
    const { ctx, page, errors } = await open(browser, D, "/chat");
    await firstTap(page);
    await page.getByRole("button", { name: /^گفتگوها/ }).tap();
    await sleep(600);
    const sheet = page.getByRole("dialog", { name: "گفتگوها" });
    rec("sheet.opens", await sheet.isVisible().catch(() => false));
    let where = await back(page);
    rec("sheet.back-closes-sheet", !(await sheet.isVisible().catch(() => false)) && where.path === "/chat", JSON.stringify(where));
    where = await back(page);
    rec("sheet.then-back-asks-to-exit", (await hintShown(page)) && where.path === "/chat", JSON.stringify(where));
    rec("errors.sheet", errors.length === 0, errors.join(" | "));
    await ctx.close();
  }

  // 4. Opened straight on another page (link, payment return): back goes to chat first, not out.
  {
    const { ctx, page, errors } = await open(browser, D, "/more/inventory");
    await firstTap(page);
    await page.getByRole("button", { name: "افزودن کالا" }).first().tap();
    await sleep(700);
    const editor = page.getByRole("dialog", { name: "افزودن کالا" });
    rec("editor.opens", await editor.isVisible().catch(() => false));
    let where = await back(page);
    rec("editor.back-closes-editor", !(await editor.isVisible().catch(() => false)) && where.path === "/more/inventory", JSON.stringify(where));
    // With unsaved text, back asks first; "stay" keeps the editor and the next back still closes it.
    await page.getByRole("button", { name: "افزودن کالا" }).first().tap();
    await sleep(700);
    await editor.getByRole("textbox").first().fill("انگشتر نقره");
    let asked = 0;
    page.once("dialog", (dialog) => {
      asked += 1;
      void dialog.dismiss();
    });
    where = await back(page);
    rec("editor.unsaved-back-asks-and-stays", asked === 1 && (await editor.isVisible().catch(() => false)), `asked=${asked} ${JSON.stringify(where)}`);
    page.once("dialog", (dialog) => {
      asked += 1;
      void dialog.accept();
    });
    where = await back(page);
    rec("editor.unsaved-back-then-confirm-closes", asked === 2 && !(await editor.isVisible().catch(() => false)) && where.path === "/more/inventory", `asked=${asked} ${JSON.stringify(where)}`);
    where = await back(page);
    await sleep(1200);
    where = await at(page);
    rec("deep.back-goes-to-chat", where.path === "/chat", JSON.stringify(where));
    where = await back(page);
    rec("deep.then-back-asks-to-exit", (await hintShown(page)) && where.path === "/chat", JSON.stringify(where));
    rec("errors.deep", errors.length === 0, errors.join(" | "));
    await ctx.close();
  }
}

async function iphone(browser) {
  // iOS has no back button: no exit hint, but back (swipe) still closes the menu first.
  const { ctx, page, errors } = await open(browser, "iPhone 13", "/chat");
  const before = await at(page);
  await firstTap(page);
  await sleep(300);
  rec("ios.no-guard-entry", (await at(page)).len === before.len);
  await page.getByRole("button", { name: "منو", exact: true }).tap();
  await sleep(500);
  let where = await back(page);
  rec("ios.back-closes-menu", !(await menuOpen(page)) && where.path === "/chat", JSON.stringify(where));
  where = await back(page);
  rec("ios.back-leaves", where.path === "about:blank", JSON.stringify(where));
  rec("errors.ios", errors.length === 0, errors.join(" | "));
  await ctx.close();
}

async function session(browser) {
  // A signed-in seller who opens the login page (landing "ورود", a home-screen shortcut) goes straight in.
  {
    const fresh = fakeJwt(now - 3600, now + 59 * 86400);
    const { ctx, page, errors, refreshes } = await open(browser, "Pixel 7", "/login", { token: fresh });
    await page.waitForURL(/\/chat/, { timeout: 8000 }).catch(() => null);
    await sleep(1000);
    rec("session.login-page-skips-to-chat", (await at(page)).path === "/chat", page.url());
    rec("session.fresh-token-not-renewed", refreshes.length === 0, `refresh calls=${refreshes.length}`);
    const where = await back(page);
    rec("session.back-does-not-show-login", where.path !== "/login", JSON.stringify(where));
    rec("errors.session-login", errors.length === 0, errors.join(" | "));
    await ctx.close();
  }
  // A 12-hour token from before the change (or a day-old one) is swapped for a fresh 60-day token on the next visit.
  for (const [name, token] of [
    ["old-12h", fakeJwt(now - 6 * 3600, now + 6 * 3600)],
    ["day-old", fakeJwt(now - 2 * 86400, now + 58 * 86400)],
  ]) {
    const { ctx, page, errors, refreshes } = await open(browser, "Pixel 7", "/chat", { token });
    const stored = await page.evaluate(() => localStorage.getItem("sozan_token"));
    const exp = JSON.parse(Buffer.from(stored.split(".")[1], "base64url").toString()).exp;
    rec(`session.${name}-token-renewed`, refreshes.length === 1 && exp - now > 59 * 86400, `refresh calls=${refreshes.length} days left=${Math.round((exp - now) / 86400)}`);
    rec(`errors.session-${name}`, errors.length === 0, errors.join(" | "));
    await ctx.close();
  }
}

const browser = await chromium.launch();
try {
  await android(browser);
  await iphone(browser);
  await session(browser);
} finally {
  await browser.close();
}
const failed = findings.filter((row) => !row.ok);
console.log(`\n${findings.length - failed.length}/${findings.length} ok`);
process.exit(failed.length ? 1 : 0);
