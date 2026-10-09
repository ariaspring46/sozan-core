"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export type QuotaLimit = "" | "daily" | "weekly";

export type AiBudget = {
  tier: "ok" | "warn" | "capped";
  note: string;
  dailyPercent: number;
  weeklyPercent: number;
  resetsAt: number;
  limit: QuotaLimit;
};

type BudgetRow = {
  tier?: string;
  note?: string;
  dailyUsedUsd?: number;
  dailyCapUsd?: number;
  weeklyUsedUsd?: number;
  weeklyCapUsd?: number;
  resetsAt?: number;
  limit?: string;
};

let cache: AiBudget | null = null;

export function quotaPercent(used: number, cap: number) {
  if (!(cap > 0)) return 0;
  return Math.min(100, (used / cap) * 100);
}

export function formatQuota(percent: number) {
  const shown = Math.round(percent * 10) / 10;
  return `${shown.toLocaleString("fa-IR", { maximumFractionDigits: 1 })}٪`;
}

function readBudget(data: BudgetRow): AiBudget {
  const limit: QuotaLimit = data.limit === "daily" || data.limit === "weekly" ? data.limit : "";
  return {
    tier: data.tier === "warn" || data.tier === "capped" ? data.tier : "ok",
    note: String(data.note || ""),
    dailyPercent: quotaPercent(Number(data.dailyUsedUsd) || 0, Number(data.dailyCapUsd) || 0),
    weeklyPercent: quotaPercent(Number(data.weeklyUsedUsd) || 0, Number(data.weeklyCapUsd) || 0),
    resetsAt: Number(data.resetsAt) || 0,
    limit,
  };
}

/** وضعیت سقف مصرف هوش ابری فروشنده از `/billing/ai-budget`؛ یک بار در هر بارگذاری. */
export function useAiBudget(): AiBudget | null {
  const [budget, setBudget] = useState<AiBudget | null>(cache);

  useEffect(() => {
    if (cache) return;
    let cancelled = false;
    void api<BudgetRow>("/billing/ai-budget")
      .then((data) => {
        cache = readBudget(data);
        if (!cancelled) setBudget(cache);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  return budget;
}
