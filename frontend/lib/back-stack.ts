"use client";

import { useEffect, useRef, useState } from "react";

/**
 * دکمهٔ «برگشت» گوشی (و مرورگر) مثل یک اپ:
 * - منو، برگه یا پنجرهٔ باز را می‌بندد؛ هر لایهٔ باز یک ورودی در تاریخچه دارد.
 * - در اندروید، روی اولین صفحهٔ پنل یک‌باره بیرون نمی‌پرد: از صفحه‌های دیگر به چت می‌رود
 *   و در چت می‌گوید «برای خروج دوباره بزن» (ورودی «نگهبان» بالای صفحهٔ اول).
 * ورودی‌ها فقط بعد از اولین لمس کاربر ساخته می‌شوند تا Chrome آن‌ها را نادیده نگیرد.
 */

type Mark = { sozanLayer?: string; sozanGuard?: boolean };
type Layer = { id: string; back: () => boolean | void };
type NavApi = {
  currentEntry: { index: number } | null;
  addEventListener: (type: "currententrychange", listener: (event: Event & { from?: { index: number } }) => void) => void;
};

const EXIT_MS = 2500;
const HOME = "/chat";

const layers: Layer[] = [];
let installed = false;
let armed = false;
let step = -1;
let linkUntil = 0;
let exitTimer = 0;
let showExitHint: ((show: boolean) => void) | null = null;
let goHome: (() => void) | null = null;

function mark(): Mark {
  const state = window.history.state as Mark | null;
  return state && typeof state === "object" ? state : {};
}

/** ورودی تازه با همان وضعیت Next (درخت صفحه) و نشان ما. */
function push(extra: Mark) {
  const state: Record<string, unknown> = { ...(window.history.state ?? {}) };
  delete state.sozanLayer;
  delete state.sozanGuard;
  window.history.pushState({ ...state, ...extra }, "");
}

function navigation(): NavApi | undefined {
  return (window as unknown as { navigation?: NavApi }).navigation;
}

/** جای این ورودی میان ورودی‌های پنل؛ صفر یعنی «برگشت» از پنل بیرون می‌برد. */
function entryIndex() {
  const index = navigation()?.currentEntry?.index;
  return typeof index === "number" ? index : -1;
}

function arm() {
  if (armed || exitTimer || entryIndex() !== 0 || !/Android/i.test(navigator.userAgent)) return;
  const activation = (navigator as Navigator & { userActivation?: { hasBeenActive: boolean } }).userActivation;
  if (activation && !activation.hasBeenActive) return;
  push({ sozanGuard: true });
  armed = true;
}

function endExitHint() {
  if (!exitTimer) return;
  window.clearTimeout(exitTimer);
  exitTimer = 0;
  showExitHint?.(false);
}

function onActivate(event: Event) {
  endExitHint();
  if (event.type === "click" && event.target instanceof Element) {
    const link = event.target.closest("a[href]");
    if (
      link instanceof HTMLAnchorElement &&
      link.origin === window.location.origin &&
      !link.target &&
      (link.pathname !== window.location.pathname || link.search !== window.location.search)
    ) {
      // صفحه عوض می‌شود؛ لایه‌ای که با آن بسته می‌شود نباید هم‌زمان «برگشت» بزند.
      linkUntil = Date.now() + 3000;
    }
  }
  arm();
}

function onPop() {
  const here = mark();
  const keep = here.sozanLayer ? layers.findIndex((layer) => layer.id === here.sozanLayer) : -1;
  if (layers.length > keep + 1) {
    const closing = layers.splice(keep + 1);
    for (let i = closing.length - 1; i >= 0; i -= 1) {
      if (closing[i].back() === false) {
        // بسته نشد (مثلاً «تغییرات ذخیره نشده»)؛ ورودی‌اش برگردد.
        layers.push(closing[i]);
        push({ sozanLayer: closing[i].id });
        break;
      }
    }
    return;
  }
  if (here.sozanLayer) {
    // لایهٔ این ورودی دیگر باز نیست (از داخلش به صفحهٔ دیگری رفتیم)؛ از رویش رد شو.
    window.history.go(step > 0 ? 1 : -1);
    return;
  }
  if (entryIndex() !== 0) return;
  if (!armed) {
    arm();
    return;
  }
  armed = false;
  if (window.location.pathname !== HOME && goHome) {
    goHome();
    return;
  }
  showExitHint?.(true);
  exitTimer = window.setTimeout(() => {
    exitTimer = 0;
    showExitHint?.(false);
    arm();
  }, EXIT_MS);
}

function install() {
  if (installed) return;
  installed = true;
  window.addEventListener("popstate", onPop);
  window.addEventListener("click", onActivate, true);
  window.addEventListener("keydown", onActivate, true);
  navigation()?.addEventListener("currententrychange", (event) => {
    const from = event.from?.index ?? -1;
    const now = entryIndex();
    if (from >= 0 && now >= 0 && now !== from) step = now > from ? 1 : -1;
  });
}

/** لایهٔ باز (منو، برگه، پنجره) با «برگشت» بسته شود. `onBack` اگر false برگرداند لایه باز می‌ماند. */
export function useBackClose(open: boolean, onBack: () => boolean | void) {
  const latest = useRef(onBack);
  useEffect(() => {
    latest.current = onBack;
  });
  useEffect(() => {
    if (!open) return;
    install();
    const layer: Layer = { id: Math.random().toString(36).slice(2, 10), back: () => latest.current() };
    push({ sozanLayer: layer.id });
    layers.push(layer);
    return () => {
      const at = layers.indexOf(layer);
      if (at < 0) return;
      layers.splice(at, 1);
      if (Date.now() < linkUntil) return;
      // با دکمه یا Escape بسته شد: ورودی‌اش را هم بردار (یک تیک بعد، تا باز شدن دوباره در همان لحظه گم نشود).
      window.setTimeout(() => {
        if (mark().sozanLayer === layer.id) window.history.back();
      }, 0);
    };
  }, [open]);
}

/** نگهبان صفحهٔ اول پنل؛ true یعنی پیام «برای خروج دوباره بزن» دیده شود. */
export function useBackGuard(home: () => void) {
  const [hint, setHint] = useState(false);
  const latest = useRef(home);
  useEffect(() => {
    latest.current = home;
  });
  useEffect(() => {
    install();
    const go = () => latest.current();
    showExitHint = setHint;
    goHome = go;
    arm();
    return () => {
      if (showExitHint === setHint) showExitHint = null;
      if (goHome === go) goHome = null;
    };
  }, []);
  return hint;
}
