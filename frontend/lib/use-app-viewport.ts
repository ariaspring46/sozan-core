"use client";

import { useEffect, useState } from "react";

const KEYBOARD_PX = 120;

export type ViewportInput = {
  vvHeight: number;
  innerHeight: number;
  vvOffsetTop: number;
  vkHeight: number;
  closedHeight: number;
};

export type ViewportFrame = {
  appHeight: number;
  keyboardInset: number;
  open: boolean;
  closedHeight: number;
};

// اگر خودِ ویوپورت کوتاه شده باشد، ارتفاع همان کافی است و نباید ارتفاع کیبورد دوباره کم شود.
export function viewportFrame(input: ViewportInput): ViewportFrame {
  const vvHeight = Math.round(input.vvHeight);
  const innerHeight = Math.round(input.innerHeight);
  const offsetTop = Math.round(input.vvOffsetTop);
  const cap = Math.round(Math.max(innerHeight, vvHeight) * 0.7);
  const vkHeight = Math.min(cap, Math.max(0, Math.round(input.vkHeight)));
  const closed = Math.round(input.closedHeight) || Math.max(vvHeight, innerHeight);
  const vvInset = Math.max(0, innerHeight - vvHeight - offsetTop);
  const shrunk = closed - vvHeight;
  const viewportTookKeyboard = vvInset > KEYBOARD_PX || shrunk > KEYBOARD_PX;
  const keyboardInset = viewportTookKeyboard || vkHeight <= KEYBOARD_PX ? 0 : vkHeight;
  const open = viewportTookKeyboard || keyboardInset > KEYBOARD_PX;
  const closedHeight = vkHeight <= KEYBOARD_PX && vvHeight >= closed - 40 ? Math.max(vvHeight, innerHeight) : closed;
  return { appHeight: vvHeight, keyboardInset, open, closedHeight };
}

type VirtualKeyboardLike = {
  boundingRect: DOMRect;
  addEventListener(type: "geometrychange", listener: EventListener): void;
  removeEventListener(type: "geometrychange", listener: EventListener): void;
};

function virtualKeyboard(): VirtualKeyboardLike | null {
  if (typeof navigator === "undefined") return null;
  const vk = (navigator as Navigator & { virtualKeyboard?: VirtualKeyboardLike }).virtualKeyboard;
  return vk ?? null;
}

function readInput(closedHeight: number): ViewportInput {
  const vv = window.visualViewport;
  const innerHeight = window.innerHeight;
  const client = document.documentElement.clientHeight || innerHeight;
  const vvRaw = vv?.height ?? innerHeight;
  return {
    vvHeight: Math.min(vvRaw, client, innerHeight),
    innerHeight: Math.max(innerHeight, client),
    vvOffsetTop: vv?.offsetTop ?? 0,
    vkHeight: virtualKeyboard()?.boundingRect?.height ?? 0,
    closedHeight,
  };
}

function applyViewport(closedHeight: number) {
  const root = document.documentElement;
  const frame = viewportFrame(readInput(closedHeight));
  root.style.setProperty("--app-height", `${frame.appHeight}px`);
  root.style.setProperty("--vv-top", `${Math.round(window.visualViewport?.offsetTop ?? 0)}px`);
  root.style.setProperty("--vv-left", `${Math.round(window.visualViewport?.offsetLeft ?? 0)}px`);
  root.style.setProperty("--vv-width", `${Math.round(window.visualViewport?.width ?? window.innerWidth)}px`);
  root.style.setProperty("--keyboard-inset", `${frame.keyboardInset}px`);
  root.classList.toggle("sozan-keyboard", frame.open);
  const pinned = root.querySelector(".sozan-app-shell, .sozan-lamp");
  if (pinned && (window.scrollY || window.scrollX)) window.scrollTo(0, 0);
  return frame;
}

/** روی همهٔ صفحه‌ها، از جمله ورود که داخل قاب پنل نیست. */
export function AppViewportSync() {
  useEffect(() => {
    let closedHeight = window.innerHeight;
    let timers: number[] = [];
    const sync = () => {
      closedHeight = applyViewport(closedHeight).closedHeight;
    };
    const reveal = () => {
      const el = document.activeElement;
      if (!(el instanceof HTMLElement) || !el.closest(".sozan-lamp")) return;
      if (el.tagName !== "INPUT" && el.tagName !== "TEXTAREA") return;
      el.scrollIntoView({ block: "center", inline: "nearest" });
    };
    const burst = () => {
      sync();
      for (const timer of timers) window.clearTimeout(timer);
      timers = [80, 240, 480].map((ms) => window.setTimeout(() => {
        sync();
        reveal();
      }, ms));
    };
    sync();
    const vv = window.visualViewport;
    vv?.addEventListener("resize", sync);
    vv?.addEventListener("scroll", sync);
    window.addEventListener("resize", sync);
    window.addEventListener("orientationchange", sync);
    const vk = virtualKeyboard();
    vk?.addEventListener("geometrychange", sync);
    document.addEventListener("focusin", burst);
    document.addEventListener("focusout", burst);
    return () => {
      vv?.removeEventListener("resize", sync);
      vv?.removeEventListener("scroll", sync);
      window.removeEventListener("resize", sync);
      window.removeEventListener("orientationchange", sync);
      vk?.removeEventListener("geometrychange", sync);
      document.removeEventListener("focusin", burst);
      document.removeEventListener("focusout", burst);
      for (const timer of timers) window.clearTimeout(timer);
    };
  }, []);
  return null;
}

export function useAppViewport() {
  const [keyboardOpen, setKeyboardOpen] = useState(false);

  useEffect(() => {
    const root = document.documentElement;
    const body = document.body;
    const prevHtmlOverflow = root.style.overflow;
    const prevBodyOverflow = body.style.overflow;
    root.style.overflow = "hidden";
    body.style.overflow = "hidden";
    const read = () => setKeyboardOpen(root.classList.contains("sozan-keyboard"));
    read();
    const obs = new MutationObserver(read);
    obs.observe(root, { attributes: true, attributeFilter: ["class"] });
    return () => {
      obs.disconnect();
      root.style.overflow = prevHtmlOverflow;
      body.style.overflow = prevBodyOverflow;
    };
  }, []);

  return keyboardOpen;
}
