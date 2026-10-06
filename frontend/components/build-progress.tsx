"use client";

import { Check, RotateCw, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { SozanMark } from "@/components/sozan-mark";

export type ProgressStep = { id: string; label: string; state: "done" | "active" | "wait" | "fail" };

const STEP_FA: Record<ProgressStep["state"], string> = { done: "انجام شد", active: "در حال انجام", wait: "منتظر", fail: "ناموفق" };

function clock(sec: number) {
  const m = Math.floor(sec / 60).toLocaleString("fa-IR");
  const s = (sec % 60).toLocaleString("fa-IR").padStart(2, "۰");
  return `${m}:${s}`;
}

function StepDot({ state }: { state: ProgressStep["state"] }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex h-6 w-6 shrink-0 items-center justify-center rounded-full",
        state === "done" && "bg-signal text-onAccent",
        state === "active" && "bg-accent/20",
        state === "fail" && "bg-danger text-onAccent",
        state === "wait" && "border border-line",
      )}
    >
      {state === "done" ? <Check size={14} strokeWidth={3} /> : null}
      {state === "fail" ? <X size={14} strokeWidth={3} /> : null}
      {state === "active" ? <span className="sozan-wave h-2 w-2 rounded-full bg-accent" /> : null}
    </span>
  );
}

/**
 * وضعیت ساخت فروشگاه: نماد زندهٔ سوزان، مرحلهٔ جاری با زمان، نوار تکه‌تکهٔ مرحله‌ها و فهرست مرحله‌ها.
 * `cover` روی پیش‌نمایش می‌نشیند و دست‌زدن به سایت نیمه‌ساخته را می‌بندد؛ بدون `cover` یک کارت معمولی است.
 */
export function BuildProgress({
  steps,
  title,
  seconds,
  live,
  failed,
  cover = false,
  onRetry,
}: {
  steps: ProgressStep[];
  title: string;
  seconds: number;
  live: boolean;
  failed: boolean;
  cover?: boolean;
  onRetry?: () => void;
}) {
  const done = steps.filter((step) => step.state === "done").length;
  const card = (
    <section
      aria-label="وضعیت ساخت فروشگاه"
      className={cn(
        "w-full max-w-sm rounded-3xl border bg-canvas p-5 text-center shadow-card",
        failed ? "border-danger/40" : "border-accent/30",
      )}
    >
      <div className="relative mx-auto flex h-20 w-20 items-center justify-center" aria-hidden="true">
        {live ? (
          <>
            <span className="sozan-ring absolute inset-1 rounded-full border-2 border-accent/50" />
            <span className="sozan-ring absolute inset-1 rounded-full border-2 border-accent/40 [animation-delay:0.8s]" />
          </>
        ) : null}
        {failed ? (
          <span className="flex h-16 w-16 items-center justify-center rounded-full bg-danger/15 text-danger">
            <X size={30} strokeWidth={2.5} />
          </span>
        ) : (
          <SozanMark className="h-14 w-14" glow={live} />
        )}
      </div>
      <p className="mt-3 text-xs font-medium text-warm">{failed ? "ساخت کامل نشد" : "در حال ساخت فروشگاه…"}</p>
      <p className={cn("mt-1 text-[17px] font-bold leading-8", failed ? "text-danger" : "text-ink")} role="status" aria-live="polite">
        {title}
      </p>
      {live ? <p className="mt-0.5 text-sm tabular-nums text-muted">{`زمان ساخت ${clock(seconds)}`}</p> : null}

      {steps.length ? (
        <>
          <div className="mt-4 flex gap-1" role="progressbar" aria-valuemin={0} aria-valuemax={steps.length} aria-valuenow={done} aria-label="پیشرفت ساخت">
            {steps.map((step) => (
              <span
                key={step.id}
                className={cn(
                  "h-1.5 flex-1 rounded-full",
                  step.state === "done" && "bg-signal",
                  step.state === "active" && "sozan-shimmer",
                  step.state === "fail" && "bg-danger",
                  step.state === "wait" && "bg-line",
                )}
              />
            ))}
          </div>
          <ol className="mt-4 space-y-2.5 text-start">
            {steps.map((step) => (
              <li key={step.id} className="flex items-center gap-3 text-[15px]">
                <StepDot state={step.state} />
                <span className={cn("leading-7", step.state === "wait" && "text-muted", step.state === "fail" && "text-danger", step.state === "active" && "font-bold text-ink")}>
                  {step.label}
                  <span className="sr-only"> — {STEP_FA[step.state]}</span>
                </span>
              </li>
            ))}
          </ol>
        </>
      ) : null}

      {live ? <p className="mt-4 text-xs leading-6 text-muted">می‌توانی از این صفحه بیرون بروی؛ ساخت ادامه پیدا می‌کند.</p> : null}
      {failed && onRetry ? (
        <Button type="button" className="mt-4 w-full gap-2" onClick={onRetry}>
          <RotateCw size={17} aria-hidden />
          دوباره بساز
        </Button>
      ) : null}
    </section>
  );
  if (!cover) return card;
  return <div className="absolute inset-0 z-20 flex items-center justify-center overflow-y-auto bg-paper/85 p-4 backdrop-blur-sm">{card}</div>;
}
