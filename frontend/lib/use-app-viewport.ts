"use client";

import { useEffect, useState } from "react";

const KEYBOARD_PX = 120;

export function useAppViewport() {
  const [keyboardOpen, setKeyboardOpen] = useState(false);

  useEffect(() => {
    const root = document.documentElement;
    const body = document.body;
    const prevHtmlOverflow = root.style.overflow;
    const prevBodyOverflow = body.style.overflow;
    root.style.overflow = "hidden";
    body.style.overflow = "hidden";

    const sync = () => {
      const vv = window.visualViewport;
      const height = Math.round(vv?.height ?? window.innerHeight);
      const offsetTop = Math.round(vv?.offsetTop ?? 0);
      const offsetLeft = Math.round(vv?.offsetLeft ?? 0);
      const width = Math.round(vv?.width ?? window.innerWidth);
      const inset = Math.max(0, window.innerHeight - height - offsetTop);
      const open = inset > KEYBOARD_PX;
      root.style.setProperty("--app-height", `${height}px`);
      root.style.setProperty("--vv-top", `${offsetTop}px`);
      root.style.setProperty("--vv-left", `${offsetLeft}px`);
      root.style.setProperty("--vv-width", `${width}px`);
      root.classList.toggle("sozan-keyboard", open);
      setKeyboardOpen(open);
      if (window.scrollY || window.scrollX) window.scrollTo(0, 0);
    };

    sync();
    const vv = window.visualViewport;
    vv?.addEventListener("resize", sync);
    vv?.addEventListener("scroll", sync);
    window.addEventListener("resize", sync);
    window.addEventListener("orientationchange", sync);
    return () => {
      vv?.removeEventListener("resize", sync);
      vv?.removeEventListener("scroll", sync);
      window.removeEventListener("resize", sync);
      window.removeEventListener("orientationchange", sync);
      root.style.overflow = prevHtmlOverflow;
      body.style.overflow = prevBodyOverflow;
      root.style.removeProperty("--app-height");
      root.style.removeProperty("--vv-top");
      root.style.removeProperty("--vv-left");
      root.style.removeProperty("--vv-width");
      root.classList.remove("sozan-keyboard");
    };
  }, []);

  return keyboardOpen;
}
