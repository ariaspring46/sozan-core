"use client";

import { useEffect, useState } from "react";

/** `matchMedia` که روی سرور و اولین رندر `false` است و بعد از mount با صفحهٔ واقعی هماهنگ می‌شود. */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const list = window.matchMedia(query);
    const read = () => setMatches(list.matches);
    read();
    list.addEventListener("change", read);
    return () => list.removeEventListener("change", read);
  }, [query]);
  return matches;
}
