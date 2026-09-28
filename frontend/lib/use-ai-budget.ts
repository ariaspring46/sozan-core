"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export type AiBudget = { tier: "ok" | "warn" | "capped"; note: string };

let cache: AiBudget | null = null;

/** وضعیت سقف مصرف هوش ابری فروشنده از `/billing/ai-budget`؛ یک بار در هر بارگذاری. */
export function useAiBudget(): AiBudget | null {
  const [budget, setBudget] = useState<AiBudget | null>(cache);

  useEffect(() => {
    if (cache) return;
    let cancelled = false;
    void api<AiBudget>("/billing/ai-budget")
      .then((data) => {
        cache = { tier: data.tier === "warn" || data.tier === "capped" ? data.tier : "ok", note: String(data.note || "") };
        if (!cancelled) setBudget(cache);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  return budget;
}
