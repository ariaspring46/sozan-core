#!/usr/bin/env node
// Mobile-first UI audit of the seller panel (owner: U). Read-only: opens pages, measures, screenshots.
//
// Unlike ui_live_audit.mjs (which opens the deployed site), this runs against ANY panel build (for example a local
// `npm run dev`) and proxies its API calls to the real API with a lab-phone session. Only GET requests reach the
// API; every write (POST/PATCH/DELETE) is answered with a stub, so the audit cannot change data.
//
//   BASE=http://127.0.0.1:3000 SOZAN_AUDIT_TOKEN_FILE=~/.sozan-audit-token node tools/ui_mobile_audit.mjs
//   ROUTES=/chat,/shop SIZES=320x640,390x844 THEMES=light,dark STRESS=1 DYNAMIC=1 node tools/ui_mobile_audit.mjs
//
//   STRESS=1   adds long Persian names, huge amounts and long URLs to the API answers (catches overflow)
//   DYNAMIC=1  also visits /campaigns/<id>, /more/docs/start, /p/<order> (and /inbox/th1 with STRESS=1)
//   SHOTS=0    measure only, no screenshots
//
// Output: docs/ui-audit-live/<LABEL>/report.md (P0/P1/P2 per route), rows.json and <route>-<w>-<theme>-<n>.png.
// Needs Playwright with Chromium (`npm i -D playwright` outside the repo is fine). Exit code is always 0; read report.md.

import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const BASE = (process.env.BASE || "http://127.0.0.1:3000").replace(/\/$/, "");
const API = "https://api.sozan-core.ir";
const LABEL = process.env.LABEL || `${new Date().toISOString().slice(0, 10)}-mobile`;
const OUT = path.join(ROOT, "docs", "ui-audit-live", LABEL);
fs.mkdirSync(OUT, { recursive: true });
const tokenFile = process.env.SOZAN_AUDIT_TOKEN_FILE || "";
if (!tokenFile || !fs.existsSync(tokenFile)) {
  console.error("SOZAN_AUDIT_TOKEN_FILE must point to a lab-phone session file (tools/lab_session.py).");
  process.exit(2);
}
const token = fs.readFileSync(tokenFile, "utf8").trim();
const SIZES = (process.env.SIZES || "360x800,390x844,412x915").split(",").map((s) => s.split("x").map(Number));
const THEMES = (process.env.THEMES || "light,dark").split(",");
const STRESS = process.env.STRESS === "1";
const SHOTS = process.env.SHOTS !== "0";
const PUBLIC = ["/", "/login", "/about", "/contact", "/terms", "/refund"];
const PANEL = ["/chat", "/shop", "/studio", "/sales", "/inbox", "/campaigns", "/brand", "/more", "/more/channels", "/more/inventory", "/more/wallet", "/more/settings", "/more/support", "/more/docs", "/onboard", "/manage", "/admin"];
let ROUTES = process.env.ROUTES ? process.env.ROUTES.split(",") : [...PUBLIC, ...PANEL];

// ---------- stress fixtures (only with STRESS=1) ----------
const LONG_FA = "این یک متن خیلی بلند فارسی است که باید در کادر پیام بدون بیرون زدن از صفحه بشکند و خط بعد برود، حتی وقتی کاربر یک کلمهٔ بسیار طولانی مثل پیش‌پردازش‌شده‌ترین‌ها را بنویسد.";
const LONG_URL = "https://sozan-test-shop-with-a-very-long-name.sozan-core.ir/products/diamond-necklace-gold-18k-with-long-slug?utm_source=instagram&utm_medium=story&utm_campaign=autumn-sale-2026";
function stress(pathname, data) {
  if (pathname === "/chat" && data && Array.isArray(data.messages)) {
    const extra = [
      { id: "s1", role: "user", text: LONG_FA, at: Date.now() / 1000 - 600 },
      { id: "s2", role: "assistant", text: LONG_FA + "\n\n" + LONG_URL, at: Date.now() / 1000 - 590 },
      { id: "s3", role: "user", text: "سلام", at: Date.now() / 1000 - 500 },
      { id: "s4", role: "assistant", text: "قیمت: ۱۲٬۴۵۰٬۰۰۰ تومان | موجودی: ۳۴ | کد: SKU-2026-DIAMOND-NECKLACE-18K-GOLD-0001", at: Date.now() / 1000 - 400 },
    ];
    data.messages = [...data.messages, ...extra];
    data.threads = [...(data.threads || []), { id: "t-long", title: "گفتگوی خیلی طولانی دربارهٔ ساخت فروشگاه جواهرات و طلا و نقره و گردنبند", at: Date.now() / 1000 - 9000 }];
  }
  if (pathname === "/catalog" && data && Array.isArray(data.products)) {
    data.products = [
      ...data.products,
      { id: "p-long", title: "گردنبند الماس‌نشان زنانه عیار ۱۸ با زنجیر ظریف و نگین درشت و گارانتی مادام‌العمر طلا و جواهر", price: 128500000, stock: 3, sku: "SKU-LONG-2026-DIAMOND-NECKLACE-18K", image: "", images: [], source: "manual" },
      { id: "p-zero", title: "کالای بی‌قیمت", price: 0, stock: 0, sku: "", image: "", images: [], source: "scan" },
    ];
  }
  const now = Date.now() / 1000;
  if (pathname === "/sales" && data) {
    data.sales = [
      { id: "s-big", title: "گردنبند الماس‌نشان زنانه عیار ۱۸ با زنجیر ظریف و نگین درشت", amount: 1250000000, customer: "علی‌اکبر محمدحسین‌زاده‌پور", channel: "اینستاگرام", status: "paid", at: now - 3600 },
      { id: "s-min", title: "انگشتر", amount: 0, customer: "", channel: "فروشگاه", status: "paid", at: now - 7200 },
      { id: "s-url", title: LONG_URL, amount: 98765432100, customer: "Maryam_Ahmadi_Jewelry_Official_Page", channel: "تلگرام", status: "paid", at: now - 9000 },
      ...(data.sales || []),
    ];
  }
  if (pathname === "/wallet" && data) {
    Object.assign(data, { available: 987654321, pendingWithdraw: 123456789, lifetimeSales: 98765432100, lifetimeCommission: 1975308642, smsUsed: 1999, smsQuota: 2000 });
    data.ledger = [{ id: "l1", kind: "sale", amount: 1250000000, note: LONG_FA, at: now - 100 }, { id: "l2", kind: "withdraw", amount: -500000000, note: "", at: now - 5000 }];
    data.withdrawals = [{ id: "w1", amount: 500000000, status: "pending", iban: "IR120170000000123456789012" }];
  }
  if (pathname === "/wallet/orders" && data && Array.isArray(data.orders)) {
    data.orders = [{ id: "o1", title: LONG_URL, amount: 125000000, status: "pending", gateway: "zarinpal", channel: "اینستاگرام", at: now, payUrl: "" }, ...data.orders];
  }
  if (pathname === "/campaigns" && Array.isArray(data)) {
    data.unshift({ id: "c-long", slug: "long-campaign", pillar: "post", title: "کمپین خیلی طولانی تخفیف ویژهٔ پاییزی گردنبندهای الماس‌نشان و طلای ۱۸ عیار با گارانتی مادام‌العمر", subtitle: LONG_FA, cta: "", assets: [], copies: [] });
  }
  if (pathname === "/channels" && data && Array.isArray(data.accounts)) {
    data.accounts = [
      { id: "a1", platform: "instagram", label: "اینستاگرام", handle: "@the_very_long_instagram_handle_name_for_testing_overflow", display: "نام نمایشی خیلی طولانی برای حساب اینستاگرام فروشگاه جواهرات", connected: true, verified: true, voiceReady: true },
      { id: "a2", platform: "telegram", label: "تلگرام", handle: "@shop", connected: true, needsReconnect: true, error: LONG_FA },
      ...data.accounts,
    ];
  }
  if (pathname === "/support/tickets" && data && Array.isArray(data.tickets)) {
    data.tickets = [{ id: "t1", subject: "مشکل در پرداخت سفارش شمارهٔ ۱۲۳۴۵۶ و عدم دریافت کد پیگیری", text: LONG_FA + " " + LONG_URL, phone: "09120000000", orderNo: "ORDER-2026-ABCDEFGHIJKLMNOP", image: "", kind: "customer", status: "open", at: now, replies: [{ text: LONG_FA, at: now }] }, ...data.tickets];
  }
  if (pathname === "/pay/receipts" && data && Array.isArray(data.receipts)) {
    data.receipts = [{ id: "RcptABCDEFGHIJKLMNOP", title: LONG_URL, amount: 1250000000, status: "pending", receipt: "", customer: "مشتری با نام خیلی طولانی و فامیلی بلندتر", at: now }, ...data.receipts];
  }
  if (pathname === "/shop" && data && data.shop) {
    data.shop.brand = "فروشگاه جواهرات و طلای ایرانی با نام بسیار طولانی برای آزمایش";
  }
  if (pathname === "/inbox/th1" && data) {
    data.thread = { id: "th1", platformLabel: "اینستاگرام", sender: "علی‌اکبر محمدحسین‌زاده‌پور از اصفهان", pending: false, paused: false, handoffReason: "مشتری درخواست تماس تلفنی کرده است" };
    data.messages = [
      { id: "m1", role: "user", text: LONG_FA, at: now - 600, kind: "inbound", platformLabel: "اینستاگرام", sender: "علی‌اکبر" },
      { id: "m2", role: "assistant", text: "پیش‌نویس پاسخ: " + LONG_FA, at: now - 500, kind: "draft" },
      { id: "m3", role: "user", text: LONG_URL, at: now - 400, kind: "inbound" },
      { id: "m4", role: "assistant", text: "ارسال نشد", at: now - 300, kind: "failed", error: "اتصال اینستاگرام قطع است" },
    ];
    data.autoReply = "draft";
  }
  if (pathname === "/inbox" && data && Array.isArray(data.threads) && data.threads.length === 0) {
    const mk = (i, name, last, unread) => ({ id: "th" + i, platform: i % 2 ? "instagram" : "telegram", name, handle: "@" + "very_long_handle_name_" + i, last, unread, at: Date.now() / 1000 - i * 3600, paused: false, status: "open" });
    data.threads = [
      mk(1, "علی‌اکبر محمدحسین‌زاده‌پور", LONG_FA, 3),
      mk(2, "Maryam", "سلام، قیمت گردنبند چنده؟", 0),
      mk(3, "فروشگاه خیلی خیلی طولانی با اسم بلند برای تست", LONG_URL, 12),
    ];
  }
  return data;
}

// ---------- in-page measurement ----------
function measure() {
  const vw = innerWidth, vh = innerHeight;
  const R = { vw, vh, docOverflowX: document.documentElement.scrollWidth - vw, docScrollH: document.documentElement.scrollHeight, overflowers: [], innerScrollX: [], small: [], smallCount: 0, inputs: [], tiny: [], clipped: [], contrast: [], latinDigits: [], english: [], noAlt: 0, iconNoLabel: [], brokenImgs: [], fixedNoSafe: [], blank: false, text: 0 };
  const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none"; };
  const label = (el) => ((el.getAttribute("aria-label") || el.textContent || el.getAttribute("name") || el.getAttribute("placeholder") || "").trim().replace(/\s+/g, " ").slice(0, 34));
  const cls = (el) => (typeof el.className === "string" ? el.className.split(/\s+/).filter(Boolean).slice(0, 4).join(".") : "");
  const sel = (el) => `${el.tagName.toLowerCase()}${el.id ? "#" + el.id : ""}${cls(el) ? "." + cls(el) : ""}`;
  const ancClips = (el) => {
    const er = el.getBoundingClientRect();
    for (let p = el.parentElement; p && p !== document.documentElement; p = p.parentElement) {
      const s = getComputedStyle(p);
      if (/(auto|scroll|hidden|clip)/.test(s.overflowX)) { const pr = p.getBoundingClientRect(); if (er.right > pr.right + 1 || er.left < pr.left - 1) return true; }
    }
    return false;
  };
  const all = [...document.querySelectorAll("body *")].filter((el) => !el.closest("nextjs-portal"));
  // overflowing elements
  for (const el of all) {
    if (!vis(el)) continue;
    const r = el.getBoundingClientRect();
    if ((r.right > vw + 1 || r.left < -1) && !ancClips(el)) {
      const s = getComputedStyle(el);
      if (s.position === "fixed" && r.width <= vw) continue;
      R.overflowers.push({ el: sel(el), left: Math.round(r.left), right: Math.round(r.right), w: Math.round(r.width), text: label(el).slice(0, 24) });
    }
  }
  R.overflowers = R.overflowers.sort((a, b) => Math.max(b.right - vw, -b.left) - Math.max(a.right - vw, -a.left)).slice(0, 6);
  // inner scrollers that scroll horizontally
  for (const el of all) {
    const s = getComputedStyle(el);
    if (/(auto|scroll)/.test(s.overflowX) && el.scrollWidth > el.clientWidth + 2 && el.clientWidth > 0 && vis(el)) R.innerScrollX.push({ el: sel(el) + (["toolbar", "tablist"].includes(el.getAttribute("role")) ? "[intentional]" : ""), sw: el.scrollWidth, cw: el.clientWidth });
  }
  R.innerScrollX = R.innerScrollX.slice(0, 6);
  // tap targets
  const seen = new Set();
  for (const el of document.querySelectorAll("a[href],button,[role=button],[role=tab],input:not([type=hidden]),select,textarea,summary,label[for]")) {
    if (!vis(el) || el.closest("nextjs-portal")) continue;
    if (el.tagName === "LABEL") continue;
    if (el.classList.contains("tap") || el.closest(".sr-only")) continue;
    if ((el.type === "checkbox" || el.type === "radio") && el.closest("label") && el.closest("label").getBoundingClientRect().height >= 44) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 44 || r.height < 44) {
      // inline links inside running text are exempt when at least 24px tall
      const inline = el.tagName === "A" && getComputedStyle(el).display === "inline";
      R.smallCount++;
      const k = label(el) + Math.round(r.width) + "x" + Math.round(r.height);
      if (!seen.has(k) && R.small.length < 14) { seen.add(k); R.small.push(`${label(el) || sel(el)} ${Math.round(r.width)}x${Math.round(r.height)}${inline ? " (inline)" : ""}`); }
    }
  }
  // inputs < 16px
  for (const el of document.querySelectorAll("input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=file]),select,textarea")) {
    if (!vis(el)) continue;
    const fs = parseFloat(getComputedStyle(el).fontSize);
    if (fs < 16) R.inputs.push(`${label(el) || sel(el)} ${fs}px`);
  }
  // text: tiny size, clipping, contrast, digits, english
  const parse = (c) => { const m = String(c).match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[\s,\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const over = (fg, bg) => ({ r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1 });
  const bgOf = (el) => {
    const layers = [];
    for (let p = el; p; p = p.parentElement) {
      const s = getComputedStyle(p);
      if (s.backgroundImage && /url\(/.test(s.backgroundImage)) return null;
      const c = parse(s.backgroundColor);
      if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; }
    }
    let base = { r: 255, g: 255, b: 255, a: 1 };
    for (let i = layers.length - 1; i >= 0; i--) base = over(layers[i], base);
    return base;
  };
  const opacityOf = (el) => { let o = 1; for (let p = el; p; p = p.parentElement) o *= parseFloat(getComputedStyle(p).opacity || "1"); return o; };
  const cseen = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = walker.nextNode())) {
    const t = (n.nodeValue || "").trim();
    if (!t) continue;
    const el = n.parentElement;
    if (!el || !vis(el) || el.closest("nextjs-portal,script,style,noscript,svg,[aria-hidden]")) continue;
    R.text++;
    const s = getComputedStyle(el);
    const fs = parseFloat(s.fontSize);
    if (fs < 12 && R.tiny.length < 10) R.tiny.push(`${t.slice(0, 22)} ${fs}px`);
    if ((s.overflow === "hidden" || s.textOverflow === "ellipsis") && el.scrollWidth > el.clientWidth + 2 && R.clipped.length < 8 && !el.closest(".sr-only") && el.clientWidth > 2) R.clipped.push(t.slice(0, 26));
    if (/[0-9]/.test(t) && /[؀-ۿ]/.test(t) && !el.closest("[dir=ltr],code,pre,a[href^='http']") && R.latinDigits.length < 8) R.latinDigits.push(t.slice(0, 30));
    if (/[A-Za-z]{3,}/.test(t) && !el.closest("[dir=ltr],code,pre,[lang=en]") && R.english.length < 8) R.english.push(t.slice(0, 30));
    const fg = parse(s.color), bg = bgOf(el);
    if (fg && bg) {
      const o = opacityOf(el);
      const eff = over({ ...fg, a: fg.a * o }, bg);
      const l1 = lum(eff), l2 = lum(bg);
      const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
      const large = fs >= 24 || (fs >= 18.66 && parseInt(s.fontWeight) >= 700);
      const need = large ? 3 : 4.5;
      const key = s.color + "|" + `${Math.round(bg.r)},${Math.round(bg.g)},${Math.round(bg.b)}` + "|" + o;
      if (ratio < need && !cseen.has(key) && R.contrast.length < 8) { cseen.add(key); R.contrast.push(`${ratio.toFixed(2)}:1 «${t.slice(0, 22)}» ${sel(el)}`); }
    }
  }
  // images / icon buttons / fixed bars
  for (const img of document.images) { if (!vis(img)) continue; if (img.complete && img.naturalWidth === 0) R.brokenImgs.push((img.currentSrc || img.src).slice(-50)); if (!img.hasAttribute("alt")) R.noAlt++; }
  for (const b of document.querySelectorAll("button,a[href],[role=button]")) {
    if (!vis(b) || b.closest("nextjs-portal")) continue;
    const hasText = (b.textContent || "").trim().length > 0;
    if (!hasText && !b.getAttribute("aria-label") && !b.getAttribute("title") && !b.querySelector("img[alt]:not([alt=''])") && R.iconNoLabel.length < 8) R.iconNoLabel.push(sel(b));
  }
  for (const el of all) {
    const s = getComputedStyle(el);
    if ((s.position === "fixed" || s.position === "sticky") && vis(el)) {
      const r = el.getBoundingClientRect();
      if (r.bottom >= vh - 2 && r.height > 20 && parseFloat(s.paddingBottom) < 8 && R.fixedNoSafe.length < 4 && !el.classList.contains("sozan-app-shell") && !el.classList.contains("login-coder-scene")) R.fixedNoSafe.push(sel(el));
    }
  }
  const bodyText = (document.body.innerText || "").trim();
  R.blank = bodyText.length < 20 || /^در حال بارگذاری/.test(bodyText);
  R.dir = document.documentElement.dir;
  R.lang = document.documentElement.lang;
  R.title = document.title;
  return R;
}

// ---------- main ----------
const browser = await chromium.launch();
const stubbed = new Set();
const apiLog = [];

async function discover() {
  const ctx = await browser.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
  const get = async (p) => { try { const r = await ctx.request.get(API + p, { timeout: 25000 }); return r.ok() ? await r.json() : null; } catch { return null; } };
  const out = {};
  const camps = await get("/campaigns");
  if (Array.isArray(camps) && camps[0]) out.campaign = camps[0].id;
  const orders = await get("/wallet/orders");
  if (orders?.orders?.[0]) out.order = orders.orders[0].id;
  await ctx.close();
  return out;
}
const ids = await discover();
const dyn = { "/campaigns/:id": ids.campaign && `/campaigns/${ids.campaign}`, "/more/docs/:slug": "/more/docs/start", "/inbox/:id": STRESS ? "/inbox/th1" : null, "/p/:id": ids.order && `/p/${ids.order}` };
if (process.env.DYNAMIC === "1") ROUTES = [...ROUTES, ...Object.values(dyn).filter(Boolean)];
console.log("routes:", ROUTES.length, "ids:", JSON.stringify(Object.fromEntries(Object.entries(ids).map(([k, v]) => [k, String(v).slice(0, 8)]))));

const rows = [];
for (const theme of THEMES) {
  for (const [w, h] of SIZES) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 2, isMobile: w < 768, hasTouch: w < 768, colorScheme: theme, locale: "fa-IR", timezoneId: "Asia/Tehran" });
    await ctx.addInitScript((t) => { try { localStorage.setItem("sozan_token", t); localStorage.setItem("sozan_onboarded", "1"); } catch {} }, token);
    await ctx.route(`${API}/**`, async (route) => {
      const req = route.request();
      const url = new URL(req.url());
      const cors = { "access-control-allow-origin": req.headers()["origin"] || BASE, "access-control-allow-headers": "*", "access-control-allow-methods": "GET,POST,PATCH,PUT,DELETE,OPTIONS", "access-control-allow-credentials": "true", vary: "origin" };
      if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
      if (req.method() !== "GET") { stubbed.add(`${req.method()} ${url.pathname}`); return route.fulfill({ status: 200, headers: { ...cors, "content-type": "application/json" }, body: JSON.stringify({ ok: true }) }); }
      try {
        if (STRESS && url.pathname === "/inbox/th1") return route.fulfill({ status: 200, headers: { ...cors, "content-type": "application/json" }, body: JSON.stringify(stress(url.pathname, {})) });
        const resp = await route.fetch();
        const headers = { ...resp.headers(), ...cors };
        delete headers["content-encoding"]; delete headers["content-length"]; delete headers["transfer-encoding"];
        let body = await resp.body();
        if (STRESS && /json/.test(headers["content-type"] || "")) { try { body = Buffer.from(JSON.stringify(stress(url.pathname, JSON.parse(body.toString("utf8"))))); } catch {} }
        apiLog.push(`${resp.status()} ${url.pathname}`);
        return route.fulfill({ status: resp.status(), headers, body });
      } catch (e) { return route.fulfill({ status: 502, headers: cors, body: "{}" }); }
    });
    for (const route of ROUTES) {
      const page = await ctx.newPage();
      const errors = [], failed = [];
      page.on("pageerror", (e) => errors.push("pageerror: " + String(e.message).slice(0, 140)));
      page.on("console", (m) => { if (m.type() === "error" && !/10\.10\.34|favicon|Failed to load resource/.test(m.text())) errors.push(m.text().slice(0, 140)); });
      page.on("response", (r) => { if (r.status() >= 400 && r.url().startsWith(BASE)) failed.push(`${r.status()} ${r.url().replace(BASE, "").slice(0, 60)}`); });
      let m = { blank: true };
      try {
        await page.goto(BASE + route, { waitUntil: "domcontentloaded", timeout: 120000 });
        await page.waitForLoadState("networkidle", { timeout: Number(process.env.IDLE_MS || 2500) }).catch(() => {});
        await page.waitForTimeout(Number(process.env.SETTLE_MS || 1000));
        m = await page.evaluate(measure);
      } catch (e) { errors.push("load: " + String(e.message).slice(0, 100)); }
      const slug = (route === "/" ? "home" : route.slice(1).replace(/\//g, "_")) + `-${w}-${theme}`;
      let shots = [];
      if (SHOTS) {
        try {
          await page.screenshot({ path: path.join(OUT, slug + "-0.png") }); shots.push(slug + "-0.png");
          // scroll the main scroller (inner container or document) and capture up to 3 more screens
          const info = await page.evaluate(() => {
            let best = null;
            for (const el of document.querySelectorAll("body *")) {
              const s = getComputedStyle(el);
              if (/(auto|scroll)/.test(s.overflowY) && el.scrollHeight > el.clientHeight + 40 && el.clientHeight > 150) { if (!best || el.scrollHeight - el.clientHeight > best.sh - best.ch) best = { el, sh: el.scrollHeight, ch: el.clientHeight }; }
            }
            if (best) { window.__sc = best.el; return { inner: true, sh: best.sh, ch: best.ch }; }
            return { inner: false, sh: document.documentElement.scrollHeight, ch: innerHeight };
          });
          const step = Math.round(info.ch * 0.85);
          for (let i = 1; i <= 3 && info.sh > info.ch + 40 && i * step < info.sh - info.ch + step; i++) {
            await page.evaluate(([inner, y]) => { if (inner) window.__sc.scrollTo(0, y); else window.scrollTo(0, y); }, [info.inner, i * step]);
            await page.waitForTimeout(350);
            await page.screenshot({ path: path.join(OUT, `${slug}-${i}.png`) }); shots.push(`${slug}-${i}.png`);
          }
          m.scrollInfo = info;
        } catch (e) { errors.push("shot: " + String(e.message).slice(0, 80)); }
      }
      rows.push({ route, w, h, theme, m, errors: [...new Set(errors)].slice(0, 5), failed: [...new Set(failed)].slice(0, 5), shots });
      fs.writeFileSync(path.join(OUT, "rows.partial.json"), JSON.stringify(rows));
      await page.close();
    }
    await ctx.close();
  }
}
await browser.close();
fs.writeFileSync(path.join(OUT, "rows.json"), JSON.stringify({ rows, stubbed: [...stubbed] }, null, 1));
// ---------- concise report ----------
const g = new Map();
const add = (route, sev, msg, where) => { const k = `${sev}|${route}|${msg}`; if (!g.has(k)) g.set(k, { route, sev, msg, where: new Set() }); g.get(k).where.add(where); };
for (const r of rows) {
  const where = `${r.w}${r.theme[0]}`;
  const m = r.m;
  if (m.blank) add(r.route, "P0", "blank or stuck", where);
  if (m.docOverflowX > 1) add(r.route, "P0", `page horizontal scroll ${m.docOverflowX}px`, where);
  if (m.overflowers?.length) add(r.route, "P1", "elements outside viewport: " + m.overflowers.slice(0, 3).map((o) => `${o.el}[${o.left}..${o.right}] «${o.text}»`).join(" ; "), where);
  const realScroll = (m.innerScrollX || []).filter((o) => !o.el.includes("[intentional]"));
  if (realScroll.length) add(r.route, "P1", "inner horizontal scroll: " + realScroll.map((o) => `${o.el} ${o.sw}>${o.cw}`).join(" ; "), where);
  if (m.inputs?.length) add(r.route, "P1", "input font <16px: " + m.inputs.join(" ; "), where);
  if (m.brokenImgs?.length) add(r.route, "P1", "broken images: " + m.brokenImgs.join(" ; "), where);
  if (m.contrast?.length) add(r.route, "P1", "low contrast: " + m.contrast.slice(0, 4).join(" ; "), where);
  if (m.errors?.length || r.errors.length) for (const e of r.errors) add(r.route, "P1", "console: " + e, where);
  for (const f of r.failed) add(r.route, "P1", "request failed " + f, where);
  if (m.smallCount > 0) add(r.route, "P2", `tap targets <44px (${m.smallCount}): ` + (m.small || []).slice(0, 8).join(" ; "), where);
  if (m.tiny?.length) add(r.route, "P2", "text <12px: " + m.tiny.slice(0, 4).join(" ; "), where);
  if (m.clipped?.length) add(r.route, "P2", "clipped text: " + m.clipped.slice(0, 4).join(" | "), where);
  if (m.latinDigits?.length) add(r.route, "P2", "latin digits in Persian text: " + m.latinDigits.slice(0, 4).join(" | "), where);
  if (m.english?.length) add(r.route, "P2", "english text: " + m.english.slice(0, 4).join(" | "), where);
  if (m.iconNoLabel?.length) add(r.route, "P2", "icon-only control without label: " + m.iconNoLabel.slice(0, 4).join(" ; "), where);
  if (m.noAlt > 0) add(r.route, "P2", `${m.noAlt} <img> without alt`, where);
  if (m.fixedNoSafe?.length) add(r.route, "P2", "fixed bottom bar without safe-area padding: " + m.fixedNoSafe.join(" ; "), where);
}
const lines = [`# audit ${LABEL} (stress=${STRESS})`, `stubbed writes: ${[...stubbed].join(", ") || "none"}`, ""];
for (const sev of ["P0", "P1", "P2"]) {
  const items = [...g.values()].filter((x) => x.sev === sev);
  lines.push(`## ${sev} (${items.length})`);
  for (const it of items) lines.push(`- \`${it.route}\` [${[...it.where].join(",")}] ${it.msg}`);
  lines.push("");
}
fs.writeFileSync(path.join(OUT, "report.md"), lines.join("\n"));
console.log(`done -> ${OUT}  P0=${[...g.values()].filter((x) => x.sev === "P0").length} P1=${[...g.values()].filter((x) => x.sev === "P1").length} P2=${[...g.values()].filter((x) => x.sev === "P2").length}`);
