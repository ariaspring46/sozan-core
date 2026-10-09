"use client";

import { formatQuota, type AiBudget } from "@/lib/use-ai-budget";

function Bar({ percent, label }: { percent: number; label: string }) {
  const width = Math.max(0, Math.min(100, percent));
  return (
    <div
      className="h-1.5 overflow-hidden rounded-full bg-line"
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(width)}
    >
      <div className="h-full rounded-full bg-accent" style={{ width: `${width}%` }} />
    </div>
  );
}

/** نوار سهمیهٔ امروز و، در نمای کامل، سهمیهٔ هفته. بازنشانی امروز همیشه نیمه‌شب تهران است. */
export function QuotaUsage({ budget, compact = false }: { budget: AiBudget; compact?: boolean }) {
  const weeklyFull = budget.limit === "weekly";
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3 text-xs">
        <span className="text-ink">سهمیهٔ امروز</span>
        <span className="font-bold text-warm">{formatQuota(budget.dailyPercent)}</span>
      </div>
      <Bar percent={budget.dailyPercent} label="سهمیهٔ امروز" />
      {compact ? null : (
        <>
          <div className="flex items-center justify-between gap-3 text-xs">
            <span className="text-ink">سهمیهٔ هفته</span>
            <span className="font-bold text-warm">{formatQuota(budget.weeklyPercent)}</span>
          </div>
          <Bar percent={budget.weeklyPercent} label="سهمیهٔ هفته" />
        </>
      )}
      <p className="text-xs leading-5 text-muted">
        {compact && weeklyFull ? "سهمیهٔ هفت‌روزه پر شده است." : "بازنشانی ۰۰:۰۰ بامداد به وقت تهران"}
      </p>
      {!compact && weeklyFull ? <p className="text-xs leading-5 text-warm">سهمیهٔ هفت‌روزه پر شده است.</p> : null}
    </div>
  );
}
