// Chat UX probe: drives the real /chat screen (a `next build` + `next start` copy) against an isolated QA API
// (SOZAN_EDGE_DRY=1, own STATE_DIR). Measures what a seller feels: does the first tap on «بفرست» send,
// does the keyboard stay open while waiting, is an error Persian and is the typed text kept, does the card
// show big buttons, does the view follow a new message. Saves screenshots next to findings.json.
//   PANEL=http://127.0.0.1:3998 TOKEN_FILE=~/chat-lab/token OUT=./chat-shots node tools/ui_chat_probe.mjs
// Run it with Playwright's chromium (see docs/ui-audit-live.md for the hub rig).
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const HOME = process.env.HOME;
const BASE = process.env.PANEL || "http://127.0.0.1:3998";
const TOKEN_FILE = (process.env.TOKEN_FILE || path.join(HOME, "chat-lab/token")).replace(/^~/, HOME);
const TOKEN = fs.readFileSync(TOKEN_FILE, "utf8").trim();
const OUT = process.env.OUT || path.join(HOME, "chat-lab/ui-shots");
const ONLY = (process.env.ONLY || "").split(",").filter(Boolean);
fs.mkdirSync(OUT, { recursive: true });
const findings = [];
function rec(id, ok, detail) {
  findings.push({ id, ok, detail });
  console.log(`${ok ? "OK  " : "FAIL"} ${id} ${detail ?? ""}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const want = (name) => !ONLY.length || ONLY.includes(name);

async function open(browser, opts = {}) {
  const { dark = false, w = 390, h = 844, fresh = true } = opts;
  const ctx = await browser.newContext({
    viewport: { width: w, height: h },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
    locale: "fa-IR",
    colorScheme: dark ? "dark" : "light",
  });
  await ctx.addInitScript((t) => {
    try {
      localStorage.setItem("sozan_token", t);
      localStorage.setItem("sozan_onboarded", "1");
    } catch {}
  }, TOKEN);
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text().slice(0, 200));
  });
  await page.goto(`${BASE}/chat`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("textarea", { timeout: 20000 });
  await sleep(1200);
  if (fresh) {
    await page.getByRole("button", { name: "گفتگوی تازه" }).click();
    await sleep(900);
  }
  return { ctx, page, errors };
}

const shot = (page, name) => page.screenshot({ path: path.join(OUT, name + ".png") });
const composer = (page) => page.locator("textarea");
const sendBtn = (page) => page.getByRole("button", { name: "بفرست", exact: true });
const box = async (loc) => {
  const b = await loc.boundingBox();
  return b ? { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) } : null;
};

let lostClicks = 0;
let sayCount = 0;
async function say(page, text, { waitMs = 0 } = {}) {
  await composer(page).click();
  await composer(page).fill(text);
  let posted = false;
  const onReq = (r) => {
    if (r.method() === "POST" && r.url().includes("/chat")) posted = true;
  };
  page.on("request", onReq);
  await sendBtn(page).click();
  await sleep(500);
  page.off("request", onReq);
  sayCount += 1;
  if (!posted && (await composer(page).inputValue()) === text) {
    // the pointer click never reached the button: the layout moved between mousedown and mouseup
    lostClicks += 1;
    await page.evaluate(() => document.querySelector("textarea").closest("form").requestSubmit());
  }
  if (waitMs) await sleep(waitMs);
}

async function waitIdle(page, timeout = 60000) {
  // the composer stays enabled while the model works (the keyboard stays open): busy ends when Sozan's typing bubble is gone
  await sleep(300);
  await page.waitForFunction(() => !document.querySelector(".sozan-wave"), null, { timeout });
  await sleep(300);
}

async function main() {
  const browser = await chromium.launch();

  // F1 empty state
  if (want("empty")) {
    const { ctx, page, errors } = await open(browser);
    await shot(page, "01-empty");
    const layout = await page.evaluate(() => {
      const r = (el) => (el ? el.getBoundingClientRect() : null);
      const ta = document.querySelector("textarea");
      const header = document.querySelector("header");
      const shell = document.querySelector(".sozan-chat");
      const scroller = ta?.closest("form")?.previousElementSibling;
      return {
        vh: window.innerHeight,
        header: r(header) && { h: Math.round(r(header).height) },
        composerBottom: ta ? Math.round(r(ta).bottom) : null,
        scrollerH: scroller ? Math.round(r(scroller).height) : null,
        chatH: shell ? Math.round(r(shell).height) : null,
        lang: document.documentElement.lang,
        dir: document.documentElement.dir,
        title: document.title,
        hasLive: Boolean(document.querySelector('[aria-live],[role="log"]')),
      };
    });
    rec("empty.layout", true, JSON.stringify(layout));
    rec("empty.composer-in-view", layout.composerBottom !== null && layout.composerBottom <= layout.vh, `bottom=${layout.composerBottom} vh=${layout.vh}`);
    rec("empty.message-area-share", true, `scroller ${layout.scrollerH}px of ${layout.vh}`);
    rec("a11y.live-region-for-new-messages", layout.hasLive, "aria-live / role=log present?");
    rec("empty.console-errors", errors.length === 0, errors.slice(0, 3).join(" | "));
    await ctx.close();
  }

  // F2 busy state, focus and keyboard behaviour
  if (want("busy")) {
    const { ctx, page } = await open(browser);
    await page.route("**/chat", async (route) => {
      if (route.request().method() === "POST") await sleep(2500);
      await route.continue();
    });
    const t0 = Date.now();
    await composer(page).click();
    const focusedBefore = await page.evaluate(() => document.activeElement?.tagName);
    await composer(page).fill("وضعیت فروشگاه چطوره؟");
    await sendBtn(page).click();
    await sleep(350);
    if ((await composer(page).inputValue()) === "وضعیت فروشگاه چطوره؟") {
      lostClicks += 1;
      sayCount += 1;
      await page.evaluate(() => document.querySelector("textarea").closest("form").requestSubmit());
      await sleep(350);
    } else {
      sayCount += 1;
    }
    const busy = await page.evaluate(() => {
      const ta = document.querySelector("textarea");
      return {
        taDisabled: Boolean(ta?.disabled),
        active: document.activeElement?.tagName,
        status: document.querySelector('[role="status"]')?.textContent?.trim() || "",
        pendingBubbles: document.querySelectorAll("article.opacity-80").length,
        sendDisabled: [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "بفرست")?.disabled,
      };
    });
    await shot(page, "02-busy");
    rec("busy.textarea-stays-enabled (keyboard stays open)", !busy.taDisabled, `disabled=${busy.taDisabled} active=${busy.active} (before: ${focusedBefore})`);
    rec("busy.pending-bubble-shown", busy.pendingBubbles > 0, `bubbles=${busy.pendingBubbles}`);
    rec("busy.status-text", Boolean(busy.status), busy.status);
    await waitIdle(page);
    const after = await page.evaluate(() => ({
      active: document.activeElement?.tagName,
      value: document.querySelector("textarea")?.value,
      lastBottomGap: (() => {
        const arts = document.querySelectorAll("article");
        const last = arts[arts.length - 1];
        const sc = document.querySelector("textarea")?.closest("form")?.previousElementSibling;
        if (!last || !sc) return null;
        return Math.round(sc.getBoundingClientRect().bottom - last.getBoundingClientRect().bottom);
      })(),
    }));
    await shot(page, "02b-after-reply");
    rec("after-reply.focus-returns-to-composer", after.active === "TEXTAREA", `active=${after.active}`);
    rec("after-reply.last-message-visible", after.lastBottomGap !== null && after.lastBottomGap >= 0, `gap=${after.lastBottomGap}`);
    rec("after-reply.latency", true, `${Date.now() - t0}ms incl. 2500ms injected delay`);
    await ctx.close();
  }

  // F3 confirm card + typed "yes" + cancel
  if (want("card")) {
    const { ctx, page } = await open(browser);
    await say(page, "برای انگشتر نقره یک پست اینستاگرام بساز");
    await waitIdle(page);
    await sleep(500);
    await shot(page, "04-card");
    const card = await page.evaluate(() => {
      const arts = [...document.querySelectorAll("article")];
      const c = arts.find((a) => a.textContent.includes("تأیید") && a.textContent.includes("انصراف"));
      if (!c) return null;
      const r = c.getBoundingClientRect();
      const btns = [...c.querySelectorAll("button")].map((b) => {
        const br = b.getBoundingClientRect();
        return { t: b.textContent.trim(), w: Math.round(br.width), h: Math.round(br.height) };
      });
      const sc = document.querySelector("textarea")?.closest("form")?.previousElementSibling;
      const sr = sc?.getBoundingClientRect();
      const bg = getComputedStyle(c).backgroundColor;
      return { text: c.textContent.trim().slice(0, 120), x: Math.round(r.x), w: Math.round(r.width), vw: window.innerWidth, btns, bg, mine: arts.filter((a) => a.className.includes("accentStrong")).map((a) => Math.round(a.getBoundingClientRect().x)) };
    });
    rec("card.present", Boolean(card), card ? card.text : "no card");
    if (card) {
      rec("card.buttons-44px", card.btns.every((b) => b.h >= 44), JSON.stringify(card.btns));
      rec("card.side", true, `card x=${card.x} w=${card.w} vw=${card.vw}; user bubble x=${card.mine.join(",")}`);
    }
    await say(page, "بله");
    await waitIdle(page);
    await sleep(400);
    await shot(page, "04b-typed-yes");
    const hold = await page.evaluate(() => {
      const arts = [...document.querySelectorAll("article")];
      return { last: arts[arts.length - 1]?.textContent.trim().slice(0, 100), count: arts.length };
    });
    rec("card.typed-yes-reply", true, hold.last);
    // can the card still be seen from the composer without scrolling?
    const cardVisible = await page.evaluate(() => {
      const arts = [...document.querySelectorAll("article")];
      const c = arts.find((a) => a.textContent.includes("تأیید") && a.textContent.includes("انصراف"));
      if (!c) return false;
      const r = c.getBoundingClientRect();
      const sc = document.querySelector("textarea")?.closest("form")?.previousElementSibling.getBoundingClientRect();
      return r.top >= sc.top && r.bottom <= sc.bottom;
    });
    rec("card.still-visible-after-typed-yes", cardVisible, "card inside the visible message area");
    await page.getByRole("button", { name: "انصراف" }).first().click();
    await waitIdle(page);
    await sleep(400);
    await shot(page, "04c-cancelled");
    const cancelled = await page.evaluate(() => {
      const arts = [...document.querySelectorAll("article")];
      return { last: arts[arts.length - 1]?.textContent.trim().slice(0, 100), buttons: arts.flatMap((a) => [...a.querySelectorAll("button")].map((b) => b.textContent.trim())).filter((t) => t === "تأیید" || t === "انصراف") };
    });
    rec("card.after-cancel", true, JSON.stringify(cancelled));
    await ctx.close();
  }

  // F4 network failures
  if (want("errors")) {
    for (const mode of ["abort", "502", "400"]) {
      const { ctx, page } = await open(browser);
      await page.route("**/chat", async (route) => {
        if (route.request().method() !== "POST") return route.continue();
        if (mode === "abort") return route.abort("failed");
        if (mode === "502") return route.fulfill({ status: 502, contentType: "text/html", body: "<html><body>Bad Gateway</body></html>" });
        return route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ detail: "متن خیلی بلند است." }) });
      });
      const draft = "برای انگشتر نقره یک پست اینستاگرام بساز لطفاً";
      await say(page, draft);
      await sleep(1200);
      const st = await page.evaluate(() => ({
        alert: [...document.querySelectorAll('[role="alert"]')].map((e) => e.textContent.trim()),
        value: document.querySelector("textarea")?.value,
        pending: document.querySelectorAll("article.opacity-80").length,
        userBubbles: [...document.querySelectorAll("article")].filter((a) => a.textContent.includes("لطفاً")).length,
        disabled: document.querySelector("textarea")?.disabled,
        retry: [...document.querySelectorAll("button")].some((b) => /دوباره|تلاش/.test(b.textContent)),
      }));
      await shot(page, `05-error-${mode}`);
      rec(`error.${mode}.message-is-persian`, st.alert.length > 0 && !/[A-Za-z]{4,}/.test(st.alert.join(" ")), JSON.stringify(st.alert));
      rec(`error.${mode}.draft-kept`, st.value === draft || st.userBubbles > 0, `textarea="${st.value}" bubbles=${st.userBubbles}`);
      rec(`error.${mode}.retry-is-one-tap`, st.value === draft, "the text is back in the composer, so the send button is the retry");
      rec(`error.${mode}.composer-usable`, !st.disabled, `disabled=${st.disabled}`);
      await ctx.close();
    }
  }

  // F5 long input
  if (want("long")) {
    const { ctx, page } = await open(browser);
    await composer(page).click();
    const h0 = await box(composer(page));
    await composer(page).fill("سلام، یک سؤال بلند دارم دربارهٔ فروشگاه زیورآلاتم. ".repeat(6));
    await sleep(300);
    const h1 = await box(composer(page));
    await shot(page, "06-long-input");
    rec("long.textarea-grows", h1 && h0 && h1.h > h0.h, `before=${h0?.h}px after=${h1?.h}px`);
    const enter = await page.evaluate(() => 0);
    void enter;
    await page.keyboard.press("Enter");
    await sleep(300);
    const sentOnEnter = await page.evaluate(() => document.querySelector("textarea")?.value === "");
    rec("long.enter-sends (mobile: expect newline instead)", true, `enter sent message: ${sentOnEnter}`);
    await waitIdle(page).catch(() => {});
    await shot(page, "06b-long-sent");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    rec("long.no-horizontal-overflow", !overflow, `scrollWidth=${await page.evaluate(() => document.documentElement.scrollWidth)}`);
    await ctx.close();
  }

  // F6 virtual keyboard (visual viewport shrinks)
  if (want("keyboard")) {
    const { ctx, page } = await open(browser);
    for (let i = 0; i < 3; i++) {
      await say(page, i === 0 ? "وضعیت فروشگاه" : "سلام");
      await waitIdle(page);
    }
    await composer(page).click();
    await page.setViewportSize({ width: 390, height: 470 });
    await sleep(700);
    await shot(page, "07-keyboard-open");
    const k = await page.evaluate(() => {
      const ta = document.querySelector("textarea");
      const r = ta.getBoundingClientRect();
      const header = document.querySelector("header")?.getBoundingClientRect();
      const arts = document.querySelectorAll("article");
      const last = arts[arts.length - 1]?.getBoundingClientRect();
      return { vh: window.innerHeight, composerBottom: Math.round(r.bottom), headerH: Math.round(header?.height || 0), lastBottom: last ? Math.round(last.bottom) : null, lastTop: last ? Math.round(last.top) : null };
    });
    rec("keyboard.composer-visible", k.composerBottom <= k.vh, JSON.stringify(k));
    rec("keyboard.last-message-visible", k.lastBottom !== null && k.lastBottom <= k.composerBottom && k.lastTop >= k.headerH, JSON.stringify(k));
    await ctx.close();
  }

  // F7 votes and tap sizes
  if (want("votes")) {
    const { ctx, page } = await open(browser);
    await say(page, "سلام");
    await waitIdle(page);
    const reqs = [];
    page.on("request", (r) => {
      if (r.url().includes("/settings/feedback")) reqs.push(r.method());
    });
    const up = page.getByRole("button", { name: "پاسخ خوب بود" }).last();
    if ((await up.count()) === 0) {
      rec("votes.skipped", true, "no thumbs: the seller has not opted in to training, so replies carry no trainId");
      await ctx.close();
    } else {
    const ub = await box(up);
    rec("votes.tap-size", ub && ub.w >= 44 && ub.h >= 44, JSON.stringify(ub));
    await up.click();
    await sleep(700);
    const state = await page.evaluate(() => [...document.querySelectorAll('button[aria-label^="پاسخ خوب"]')].map((b) => ({ l: b.getAttribute("aria-label"), d: b.disabled })));
    rec("votes.after-click", reqs.length === 1, `requests=${reqs.join(",")} state=${JSON.stringify(state.slice(-2))}`);
    await shot(page, "08-vote");
    await ctx.close();
    }
  }

  // F8 reload: flash of the welcome screen before history
  if (want("reload")) {
    const { ctx, page } = await open(browser);
    await say(page, "سلام");
    await waitIdle(page);
    await page.reload({ waitUntil: "domcontentloaded" });
    const timeline = [];
    const t0 = Date.now();
    for (let i = 0; i < 40; i++) {
      timeline.push(
        await page.evaluate(() => {
          const t = document.body.innerText;
          return t.includes("سلام، من سوزانم") ? "welcome" : document.querySelectorAll("article").length ? "messages" : document.querySelector("textarea") ? "empty-shell" : "blank";
        }),
      );
      await sleep(60);
    }
    const flat = timeline.filter((v, i) => i === 0 || v !== timeline[i - 1]).join(" → ");
    rec("reload.no-welcome-flash", !flat.includes("welcome"), `states: ${flat} (${Date.now() - t0}ms)`);
    await ctx.close();
  }

  // F9 dark card
  if (want("dark")) {
    const { ctx, page } = await open(browser, { dark: true });
    await say(page, "برای انگشتر نقره یک پست اینستاگرام بساز");
    await waitIdle(page);
    await sleep(500);
    await shot(page, "09-dark-card");
    await ctx.close();
  }

  // F10 long history scroll behaviour
  if (want("scroll")) {
    const { ctx, page } = await open(browser);
    for (let i = 0; i < 8; i++) {
      await say(page, i % 2 ? "سلام" : "وضعیت فروشگاه");
      await waitIdle(page);
    }
    await shot(page, "10-history-bottom");
    await page.evaluate(() => {
      const sc = document.querySelector("textarea")?.closest("form")?.previousElementSibling;
      sc.scrollTop = 0;
    });
    await sleep(300);
    await say(page, "سلام");
    await waitIdle(page);
    const away = await page.evaluate(() => {
      const sc = document.querySelector("textarea")?.closest("form")?.previousElementSibling;
      return { top: Math.round(sc.scrollTop), max: Math.round(sc.scrollHeight - sc.clientHeight) };
    });
    await shot(page, "10b-new-reply-while-scrolled-up");
    rec("scroll.send-while-scrolled-up-jumps-to-latest", away.top >= away.max - 4, `scrollTop=${away.top} max=${away.max} (the user just sent: view should follow)`);
    await ctx.close();
  }

  rec("send.tap-while-typing-sends-first-time", lostClicks === 0, `${lostClicks} of ${sayCount} sends needed a second try (button moved under the finger when the keyboard closed)`);
  fs.writeFileSync(path.join(OUT, "findings.json"), JSON.stringify(findings, null, 1));
  await browser.close();
}

main().catch((e) => {
  console.error("FATAL", e);
  process.exit(1);
});
