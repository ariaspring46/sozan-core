"use client";

import { MutableRefObject, useEffect } from "react";

/** پیامی که سوزان خودش در چت گذاشته (سفارش تازه، رسید، یادآوری): app-shell خبر می‌دهد و چت باز همان را می‌خواند. */
export function useSozanEvents(load: () => Promise<void>, busyRef: MutableRefObject<boolean>) {
  useEffect(() => {
    const fresh = () => {
      if (!busyRef.current) void load().catch(() => undefined);
    };
    window.addEventListener("sozan:events", fresh);
    return () => window.removeEventListener("sozan:events", fresh);
  }, [load, busyRef]);
}
