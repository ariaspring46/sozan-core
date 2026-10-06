#!/usr/bin/env node
// Live mobile audit of the seller panel (owner: U). Read-only: opens pages, measures, screenshots.
//
//   node tools/ui_live_audit.mjs                       # public pages, 3 phone sizes, light+dark
//   SOZAN_AUDIT_TOKEN_FILE=/path/token node tools/ui_live_audit.mjs   # also the signed-in panel (lab phone only)
//   BASE=http://localhost:3000 ROUTES=/chat,/shop node tools/ui_live_audit.mjs --desktop
//
// Token: a lab-phone session minted by X5 with tools/lab_session.py (never a real seller, never printed).
// Output: docs/ui-audit-live/<YYYY-MM-DD>/report.md, report.json, <route>-<w>-<theme>.png
// Exit 1 when a P0 is found (blank page, failed /_next chunk, horizontal scroll, page error).

import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const BASE = (process.env.BASE || "https://app.sozan-core.ir").replace(/\/$/, "");
const PUBLIC = ["/", "/login", "/about", "/contact", "/terms", "/refund"];
const PANEL = ["/chat", "/shop", "/studio", "/sales", "/inbox", "/campaigns", "/brand", "/more",
  "/more/channels", "/more/inventory", "/more/wallet", "/more/settings", "/more/support", "/more/docs"];
const PHONES = [[360, 800], [390, 844], [412, 915]];
const DESKTOP = process.argv.includes("--desktop") ? [[1440, 900]] : [];
// Iranian ISP filter injects http://10.10.34.35; it is not our app.
const IGNORE = [/10\.10\.34\.3[0-9]/, /favicon/];

const tokenFile = process.env.SOZAN_AUDIT_TOKEN_FILE;
const token = tokenFile && fs.existsSync(tokenFile) ? fs.readFileSync(tokenFile, "utf8").trim() : "";
const routes = process.env.ROUTES ? process.env.ROUTES.split(",") : [...PUBLIC, ...(token ? PANEL : [])];
const day = new Date().toISOString().slice(0, 10);
const outDir = path.join(ROOT, "docs", "ui-audit-live", day);
fs.mkdirSync(outDir, { recursive: true });

// Runs inside the page. Every number is measured, not guessed.
function measure() {
  const vw = window.innerWidth;
  const out = { overflowX: document.documentElement.scrollWidth - vw, small: [], inputs: [], clipped: [], offscreen: [], images: [], vh: [], blank: false };
  const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none"; };
  const label = (el) => (el.getAttribute("aria-label") || el.textContent || el.getAttribute("name") || el.tagName).trim().replace(/\s+/g, " ").slice(0, 40);
  for (const el of document.querySelectorAll("a[href],button,[role=button],input:not([type=hidden]),select,textarea,[role=tab]")) {
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    // the real touch area: `.tap` widens it with an invisible ::after, and a checkbox inside a label is tapped through the label
    const after = getComputedStyle(el, "::after");
    const hit = after.content !== "none" && after.position === "absolute" ? { w: parseFloat(after.width) || 0, h: parseFloat(after.height) || 0 } : { w: 0, h: 0 };
    const lab = el.closest("label") ? el.closest("label").getBoundingClientRect() : { width: 0, height: 0 };
    const touchW = Math.max(r.width, hit.w, lab.width);
    const touchH = Math.max(r.height, hit.h, lab.height);
    if (touchW < 44 || touchH < 44) out.small.push(`${label(el)} ${Math.round(touchW)}x${Math.round(touchH)}`);
    if (r.right > vw + 1 || r.left < -1) out.offscreen.push(`${label(el)} left=${Math.round(r.left)} right=${Math.round(r.right)}`);
  }
  for (const el of document.querySelectorAll("input:not([type=hidden]):not([type=checkbox]):not([type=radio]),select,textarea")) {
    const fs = parseFloat(getComputedStyle(el).fontSize);
    if (visible(el) && fs < 16) out.inputs.push(`${label(el)} font ${fs}px (iOS zooms below 16px)`);
  }
  for (const el of document.querySelectorAll("h1,h2,h3,p,span,button,a,label,td")) {
    if (!visible(el) || !el.textContent.trim() || el.classList.contains("sr-only")) continue; // sr-only is clipped on purpose
    const s = getComputedStyle(el);
    if ((s.overflow === "hidden" || s.textOverflow === "ellipsis" || s.overflowX === "hidden") && el.scrollWidth > el.clientWidth + 2) out.clipped.push(label(el));
  }
  for (const img of document.images) if (img.complete && img.naturalWidth === 0 && visible(img)) out.images.push(img.currentSrc || img.src);
  for (const el of document.querySelectorAll("body *")) {
    const s = getComputedStyle(el);
    if ((s.position === "fixed" || s.position === "sticky") && visible(el)) {
      const r = el.getBoundingClientRect();
      if (r.bottom >= window.innerHeight - 2 && r.height < window.innerHeight * 0.4 && parseFloat(s.paddingBottom) < 8) out.vh.push(`${label(el)}: fixed bottom bar without safe-area padding`);
    }
  }
  out.small = [...new Set(out.small)].slice(0, 15);
  out.clipped = [...new Set(out.clipped)].slice(0, 10);
  const text = (document.body.innerText || "").trim();
  out.blank = text.length < 20 || /^در حال بارگذاری/.test(text);
  out.dir = document.documentElement.dir;
  return out;
}

const browser = await chromium.launch();
const rows = [];
for (const theme of ["light", "dark"]) {
  for (const [w, h] of [...PHONES, ...DESKTOP]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, isMobile: w < 768, hasTouch: w < 768, colorScheme: theme, locale: "fa-IR" });
    if (token) await ctx.addInitScript((t) => { localStorage.setItem("sozan_token", t); localStorage.setItem("sozan_onboarded", "1"); }, token);
    for (const route of routes) {
      const page = await ctx.newPage();
      const failed = [], errors = [];
      page.on("response", (r) => { if (r.status() >= 400 && r.url().startsWith(BASE) && !IGNORE.some((x) => x.test(r.url()))) failed.push(`${r.status()} ${r.url().replace(BASE, "")}`); });
      page.on("console", (m) => { if (m.type() === "error" && !IGNORE.some((x) => x.test(m.text()))) errors.push(m.text().slice(0, 160)); });
      page.on("pageerror", (e) => errors.push(`pageerror: ${String(e.message).slice(0, 160)}`));
      let m = { blank: true };
      try {
        await page.goto(BASE + route, { waitUntil: "networkidle", timeout: 30000 });
        await page.waitForTimeout(800);
        m = await page.evaluate(measure);
      } catch (e) { errors.push(`load: ${String(e.message).slice(0, 120)}`); }
      const shot = `${route === "/" ? "home" : route.slice(1).replace(/\//g, "_")}-${w}-${theme}.png`;
      await page.screenshot({ path: path.join(outDir, shot), fullPage: true }).catch(() => {});
      const chunkFail = failed.some((f) => /\/_next\//.test(f) && /^5|^404/.test(f));
      const p0 = [chunkFail && "a /_next chunk failed: page cannot run", m.blank && "blank or stuck on loading", m.overflowX > 1 && `horizontal scroll ${m.overflowX}px`, errors.some((e) => e.startsWith("pageerror")) && "uncaught page error", m.dir && m.dir !== "rtl" && "html dir is not rtl"].filter(Boolean);
      const p1 = [m.offscreen?.length && `off-screen controls: ${m.offscreen.join("; ")}`, m.images?.length && `broken images: ${m.images.join(", ")}`, m.inputs?.length && `inputs < 16px: ${m.inputs.join("; ")}`, failed.length && !chunkFail && `failed requests: ${failed.join(", ")}`].filter(Boolean);
      const p2 = [m.small?.length && `tap targets < 44px: ${m.small.join("; ")}`, m.clipped?.length && `clipped text: ${m.clipped.join(" | ")}`, m.vh?.length && m.vh.join("; "), errors.length && `console errors: ${errors.slice(0, 3).join(" | ")}`].filter(Boolean);
      rows.push({ route, width: w, theme, shot, p0, p1, p2 });
      await page.close();
    }
    await ctx.close();
  }
}
await browser.close();

const count = (k) => rows.reduce((n, r) => n + r[k].length, 0);
const md = [`# بازبینی زندهٔ موبایل ${day}`, "", `پایه: ${BASE} · ورود: ${token ? "بله (شمارهٔ آزمایشگاه)" : "خیر (فقط صفحه‌های عمومی)"} · P0=${count("p0")} P1=${count("p1")} P2=${count("p2")}`, ""];
// One line per (route, finding), listing every size/theme where it showed, so the report stays short.
for (const sev of ["p0", "p1", "p2"]) {
  const grouped = new Map();
  for (const r of rows) for (const item of r[sev]) {
    const key = `${r.route}\u0000${item}`;
    if (!grouped.has(key)) grouped.set(key, { route: r.route, item, where: [], shot: r.shot });
    grouped.get(key).where.push(`${r.width}/${r.theme}`);
  }
  if (!grouped.size) continue;
  md.push(`## ${sev.toUpperCase()}`, "");
  for (const g of grouped.values()) md.push(`- \`${g.route}\` (${g.where.join("، ")}): ${g.item} ([عکس](${g.shot}))`);
  md.push("");
}
fs.writeFileSync(path.join(outDir, "report.md"), md.join("\n") + "\n");
fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(rows, null, 1) + "\n");
console.log(`ui_live_audit: P0=${count("p0")} P1=${count("p1")} P2=${count("p2")} → ${path.relative(ROOT, outDir)}/report.md`);
process.exit(count("p0") ? 1 : 0);
