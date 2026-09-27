"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type PlanRow = { id: string; label: string; priceToman?: number };
type SettingsPlan = { plan?: string; subscription?: { plan?: string; label?: string; plans?: PlanRow[] } };

export type PlanInfo = { id: string; label: string; canUpgrade: boolean };

let cache: PlanInfo | null = null;

/** پلن فعلی فروشنده از `/settings`؛ یک بار در هر بارگذاری صفحه خوانده می‌شود. */
export function usePlan(): PlanInfo | null {
  const [plan, setPlan] = useState<PlanInfo | null>(cache);

  useEffect(() => {
    if (cache) return;
    let cancelled = false;
    void api<SettingsPlan>("/settings")
      .then((data) => {
        const id = String(data.subscription?.plan || data.plan || "free");
        const plans = [...(data.subscription?.plans || [])].sort((a, b) => (a.priceToman || 0) - (b.priceToman || 0));
        const current = plans.find((row) => row.id === id);
        const top = plans[plans.length - 1];
        const info: PlanInfo = {
          id,
          label: data.subscription?.label || current?.label || (id === "free" ? "رایگان" : id),
          canUpgrade: Boolean(top && top.id !== id),
        };
        cache = info;
        if (!cancelled) setPlan(info);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  return plan;
}
