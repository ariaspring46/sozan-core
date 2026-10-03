// Chat gallery: renders the /chat screen with fixture messages (question with quick answers, confirm cards, a finished post,
// a running compose, a build note, the typing indicator) and saves screenshots; also measures layout rules.
// Everything the page reads from the API is stubbed in the browser; nothing is written.
//   PANEL=http://127.0.0.1:3998 API=http://127.0.0.1:8014 TOKEN_FILE=~/shop-lab/token OUT=./chat-gallery node tools/ui_chat_visual.mjs
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const HOME = process.env.HOME;
const BASE = process.env.PANEL || "http://127.0.0.1:3998";
const API = process.env.API || "http://127.0.0.1:8014";
const TOKEN = fs.readFileSync((process.env.TOKEN_FILE || path.join(HOME, "shop-lab/token")).replace(/^~/, HOME), "utf8").trim();
const OUT = process.env.OUT || path.join(HOME, "shop-lab/chat-gallery");
fs.mkdirSync(OUT, { recursive: true });
const findings = [];
const rec = (id, ok, detail) => {
  findings.push({ id, ok, detail });
  console.log(`${ok ? "OK  " : "FAIL"} ${id} ${detail ?? ""}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const now = Math.floor(Date.now() / 1000);
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");

const SCENES = {
  empty: [],
  talk: [
    { id: "1", role: "user", text: "سلام، می‌خوام برای فروشگاهم سایت بسازم", at: now - 300 },
    { id: "2", role: "assistant", text: "سلام! خوش اومدی. بگو ببینم چی می‌فروشی و مشتری‌هات بیشتر چه کسانی هستن؟", at: now - 290 },
    { id: "3", role: "user", text: "انگشتر و گردنبند نقره دست‌ساز، مشتری‌ها بیشتر خانم‌های جوان", at: now - 200 },
    {
      id: "4", role: "assistant", kind: "ask", at: now - 190,
      text: "چه خوب، نقرهٔ دست‌ساز! حس سایتت چطور باشه؟ یکی از این‌ها را بزن یا خودت بنویس.",
      options: ["لوکس و خلوت", "خیابانی و پرانرژی", "بوتیک گرم و خانوادگی", "تو انتخاب کن"],
    },
  ],
  confirm: [
    { id: "1", role: "user", text: "برای انگشتر نقره یک پست اینستاگرام بساز", at: now - 60 },
    { id: "2", role: "assistant", kind: "confirm", confirmId: "c1", tool: "studio_chat", at: now - 50, text: "پست اینستاگرام برای «انگشتر نقره» ساخته شود؟ عکس و کپشن آماده می‌شود و فقط وقتی بگویی منتشر می‌شود." },
  ],
  confirm_build: [
    { id: "1", role: "user", text: "فروشگاه را از نو بساز", at: now - 60 },
    { id: "2", role: "assistant", kind: "confirm", confirmId: "c2", tool: "shop_chat", at: now - 50, text: "فروشگاه از نو ساخته شود؟ سایت فعلی با طرح تازه جایگزین می‌شود و چند دقیقه طول می‌کشد." },
  ],
  post: [
    { id: "1", role: "user", text: "برای انگشتر نقره یک پست اینستاگرام بساز", at: now - 400 },
    {
      id: "2", role: "assistant", at: now - 300, campaignId: "camp1",
      text: "پست آماده است؛ با حس گرم و دست‌ساز. اگر تخفیف یا مناسبتی داری بگو تا در کپشن بیاورم.",
      attachments: [{ kind: "image", name: "a.png" }],
      captions: { instagram: "انگشتر نقرهٔ دست‌ساز؛ هر قطعه با دقت ساخته می‌شود و حس گرم یک هدیهٔ خاص را می‌دهد.", telegram: "انگشتر نقرهٔ دست‌ساز", whatsapp: "انگشتر نقرهٔ دست‌ساز؛ برای سفارش پیام بده." },
    },
  ],
  composing: [
    { id: "1", role: "user", text: "یک استوری برای تخفیف یلدا بساز", at: now - 40 },
    { id: "2", role: "assistant", text: "دارم استوری یلدا را می‌سازم.", at: now - 35, compose: { status: "running", jobId: "j", stage: "image", startedAt: now - 22 } },
  ],
  build: [
    { id: "1", role: "user", text: "آره، شروع کن", at: now - 80 },
    { id: "2", role: "assistant", kind: "build", text: "در حال ساخت فروشگاه. در حال طراحی ظاهر و چیدن کالاها…", at: now - 70 },
  ],
};

const posts = [];

async function shoot(browser, scene, { w = 390, h = 844, dark = false, busy = false, name, mic = false } = {}) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 2, isMobile: w < 800, hasTouch: w < 800, locale: "fa-IR", colorScheme: dark ? "dark" : "light" });
  if (mic) await ctx.grantPermissions(["microphone"], { origin: BASE });
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
  const json = (body) => ({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify(body) });
  const messages = SCENES[scene];
  const pending = scene === "confirm" ? { id: "c1" } : scene === "confirm_build" ? { id: "c2" } : null;
  await page.route(`${API}/**`, async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    const m = req.method();
    if (p === "/chat" && m === "GET") return route.fulfill(json({ messages, pendingConfirm: pending, brand: "نقره‌خانه", threadId: "t1", threads: [{ id: "t1", title: "گفتگو" }] }));
    if (p === "/chat" && m === "POST") {
      posts.push(JSON.parse(req.postData() || "{}"));
      await sleep(busy ? 20000 : 600);
      return route.fulfill(json({ messages: [...messages, { id: "u9", role: "user", text: "x", at: now }, { id: "a9", role: "assistant", text: "باشه.", at: now }], pendingConfirm: null, threadId: "t1" }));
    }
    if (p === "/studio" && m === "GET") return route.fulfill(json({ targets: [{ id: "instagram", label: "اینستاگرام", ready: true }, { id: "telegram", label: "تلگرام", ready: true }] }));
    if (/\/(media|assets)|campaigns\/camp1\/media|public/.test(p) || /\.png$/.test(p)) return route.fulfill({ status: 200, contentType: "image/png", headers: { "access-control-allow-origin": "*" }, body: PNG });
    return route.continue();
  });
  await page.goto(`${BASE}/chat`, { waitUntil: "domcontentloaded" });
  await sleep(4500);
  if (busy) {
    await page.locator("textarea").first().fill("یک پست بساز");
    await page.getByRole("button", { name: "بفرست", exact: true }).click();
    await sleep(1800);
  }
  const m = await page.evaluate(() => ({
    overflow: document.documentElement.scrollWidth > innerWidth + 1,
    small: [...document.querySelectorAll("button, a[href], textarea, input, select")].filter((el) => {
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && cs.visibility !== "hidden" && (r.height < 40 || r.width < 40) && !el.classList.contains("tap");
    }).map((el) => `${(el.getAttribute("aria-label") || el.textContent || el.tagName).trim().slice(0, 20)} ${Math.round(el.getBoundingClientRect().width)}x${Math.round(el.getBoundingClientRect().height)}`),
  }));
  await page.screenshot({ path: path.join(OUT, `${name || scene}${dark ? "-dark" : ""}-${w}.png`) });
  rec(`${name || scene}.${w}${dark ? ".dark" : ""}.no-overflow`, !m.overflow, "");
  // fingers only matter on a phone; the desktop sidebar has compact mouse-sized controls
  if (w < 800) rec(`${name || scene}.${w}${dark ? ".dark" : ""}.tap-targets`, m.small.length === 0, m.small.slice(0, 4).join(" | "));
  rec(`${name || scene}.${w}${dark ? ".dark" : ""}.console`, errors.length === 0, errors.slice(0, 2).join(" | "));
  return { ctx, page };
}

async function interactions(browser) {
  // a tap on a quick answer sends exactly that text
  let { ctx, page } = await shoot(browser, "talk", { name: "tap-answer" });
  posts.length = 0;
  await page.getByRole("button", { name: "بوتیک گرم و خانوادگی", exact: true }).click();
  await sleep(1500);
  rec("ask.tap-sends-the-option", posts.length === 1 && posts[0].text === "بوتیک گرم و خانوادگی", JSON.stringify(posts[0] || {}));
  rec("ask.options-gone-after-answer", (await page.getByRole("button", { name: "لوکس و خلوت", exact: true }).count()) === 0, "answered question has no taps");
  await ctx.close();

  // the confirm card: big buttons, the right ids, a title that names the job
  ({ ctx, page } = await shoot(browser, "confirm", { name: "tap-confirm" }));
  const card = await page.evaluate(() => {
    const c = [...document.querySelectorAll("article")].find((a) => a.textContent.includes("انصراف"));
    const btns = [...(c?.querySelectorAll("button") || [])].map((b) => ({ t: b.textContent.trim(), h: Math.round(b.getBoundingClientRect().height) }));
    return { title: c?.textContent.includes("ساخت محتوا"), btns };
  });
  rec("card.names-the-job-and-has-big-buttons", Boolean(card.title) && card.btns.length === 2 && card.btns.every((b) => b.h >= 44), JSON.stringify(card));
  posts.length = 0;
  await page.getByRole("button", { name: /^تأیید/ }).click();
  await sleep(1500);
  rec("card.confirm-posts-its-id", posts.length === 1 && posts[0].confirmId === "c1", JSON.stringify(posts[0] || {}));
  await ctx.close();
  ({ ctx, page } = await shoot(browser, "confirm", { name: "tap-cancel" }));
  posts.length = 0;
  await page.getByRole("button", { name: "انصراف", exact: true }).click();
  await sleep(1500);
  rec("card.cancel-posts-its-id", posts.length === 1 && posts[0].cancelId === "c1", JSON.stringify(posts[0] || {}));
  await ctx.close();

  // the typing bubble sits on the assistant's side while the reply is awaited
  ({ ctx, page } = await shoot(browser, "talk", { busy: true, name: "typing-side" }));
  const side = await page.evaluate(() => {
    const bubble = document.querySelector("[data-typing]");
    const mine = [...document.querySelectorAll("article")].find((a) => a.className.includes("accentStrong"));
    const r = bubble?.getBoundingClientRect();
    const u = mine?.getBoundingClientRect();
    return { typing: r ? Math.round(r.left + r.width / 2) : -1, mine: u ? Math.round(u.left + u.width / 2) : -1, vw: innerWidth, orb: document.querySelectorAll("[data-typing] canvas").length, label: document.querySelector("[data-typing]")?.textContent.trim() };
  });
  rec("typing.on-the-assistant-side", side.typing > 0 && side.typing < side.vw / 2 && side.mine > side.vw / 2 && side.orb === 1 && Boolean(side.label), JSON.stringify(side));
  await ctx.close();

  // empty chat: the orb is drawn and a starter card puts its opening words in the box (nothing is sent)
  ({ ctx, page } = await shoot(browser, "empty", { name: "starter" }));
  const orb = await page.evaluate(() => {
    const c = document.querySelector("canvas");
    if (!c) return { ok: false };
    const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
    let lit = 0;
    for (let i = 3; i < d.length; i += 4) if (d[i] > 30) lit += 1;
    return { ok: true, lit, cards: document.querySelectorAll('[aria-label="شروع سریع"] button').length };
  });
  rec("welcome.orb-drawn-and-four-cards", orb.ok && orb.lit > 500 && orb.cards === 4, JSON.stringify(orb));
  posts.length = 0;
  await page.getByRole("button", { name: /ساخت پست/ }).click();
  await sleep(400);
  const box = await page.evaluate(() => ({ value: document.querySelector("textarea")?.value, focused: document.activeElement?.tagName }));
  rec("welcome.card-fills-the-box", box.value === "یک پست اینستاگرام بساز برای " && box.focused === "TEXTAREA" && posts.length === 0, JSON.stringify(box));
  await ctx.close();

  // voice: Chromium's fake microphone; the listening panel with the orb shows, stop leaves a voice file ready to send
  ({ ctx, page } = await shoot(browser, "talk", { name: "voice", mic: true }));
  await page.getByRole("button", { name: "ضبط صدا", exact: true }).click();
  await sleep(1600);
  const listening = await page.evaluate(() => ({
    panel: [...document.querySelectorAll('[role="status"]')].some((el) => el.textContent.includes("دارم گوش می‌دهم")),
    orbs: document.querySelectorAll("form canvas").length,
  }));
  await page.screenshot({ path: path.join(OUT, "voice-listening-390.png") });
  rec("voice.listening-panel", listening.panel && listening.orbs === 1, JSON.stringify(listening));
  await page.getByRole("button", { name: "پایان ضبط", exact: true }).click();
  await sleep(900);
  const after = await page.evaluate(() => ({
    chip: document.querySelector("form")?.textContent.includes("صدا · voice."),
    panel: [...document.querySelectorAll('[role="status"]')].some((el) => el.textContent.includes("دارم گوش می‌دهم")),
  }));
  rec("voice.stop-leaves-a-file", Boolean(after.chip) && !after.panel, JSON.stringify(after));
  await ctx.close();
}

async function main() {
  const browser = await chromium.launch({ args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"] });
  await interactions(browser);
  for (const scene of Object.keys(SCENES)) {
    const { ctx } = await shoot(browser, scene);
    await ctx.close();
  }
  const typing = await shoot(browser, "talk", { busy: true, name: "typing" });
  await typing.ctx.close();
  for (const scene of ["empty", "talk", "confirm", "post"]) {
    const dark = await shoot(browser, scene, { dark: true });
    await dark.ctx.close();
  }
  const narrow = await shoot(browser, "post", { w: 360, h: 640 });
  await narrow.ctx.close();
  const wide = await shoot(browser, "talk", { w: 1280, h: 800 });
  await wide.ctx.close();
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
