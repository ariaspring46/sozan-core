"use client";

import { ReactNode, useEffect, useState } from "react";
import Link from "next/link";
import { Check, CheckCircle2, Hammer, ImageIcon, Megaphone, MessageSquareText, Package, PencilRuler, Send, Sparkles, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { SozanMark } from "@/components/sozan-mark";

/** ساعت پیام: امروز فقط ساعت، قدیمی‌تر روز و ساعت. */
export function shortWhen(at: number): string {
  if (!at) return "";
  const date = new Date(at * 1000);
  const now = new Date();
  const time = date.toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit" });
  if (date.toDateString() === now.toDateString()) return time;
  return `${date.toLocaleDateString("fa-IR", { day: "numeric", month: "long" })}، ${time}`;
}

/** آواتار سوزان کنار حباب؛ هنگام انتظار حلقهٔ نرمی دورش می‌چرخد. */
export function Avatar({ live = false }: { live?: boolean }) {
  return (
    <span className="relative mb-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center">
      {live ? <span aria-hidden className="sozan-ring absolute inset-0 rounded-full border-2 border-accent/50" /> : null}
      <SozanMark className="h-7 w-7" glow={false} />
    </span>
  );
}

/** جای خالی هم‌عرضِ آواتار تا حباب‌های پشت‌سرهم یک‌خط بمانند. */
export function AvatarSpacer() {
  return <span aria-hidden className="inline-block h-8 w-8 shrink-0" />;
}

/**
 * وقتی مدل دارد می‌نویسد: همان‌جا که جواب می‌آید (سمت سوزان) یک حباب با نقطه‌های موجی و دو خط سایه‌ای که با رسیدن جواب جایش را می‌دهد.
 * هر چه انتظار طولانی‌تر شود متن صادقانه‌تر می‌شود تا کاربر فکر نکند برنامه قفل کرده.
 */
export function TypingBubble({ label }: { label: string }) {
  return (
    <div className="ms-auto flex w-fit max-w-[86%] flex-col gap-1" role="status" aria-live="polite">
      <div className="flex items-end gap-2">
        <div className="min-w-[8.5rem] rounded-2xl rounded-bl-md border border-line/70 bg-canvas px-4 py-3 shadow-card">
          <span className="flex items-center gap-1.5" aria-hidden>
            <span className="sozan-wave h-2 w-2 rounded-full bg-accent" />
            <span className="sozan-wave h-2 w-2 rounded-full bg-accent" />
            <span className="sozan-wave h-2 w-2 rounded-full bg-accent" />
          </span>
          <span className="mt-2.5 block space-y-1.5" aria-hidden>
            <span className="sozan-shimmer block h-2.5 w-36 rounded-full" />
            <span className="sozan-shimmer block h-2.5 w-24 rounded-full" />
          </span>
        </div>
        <Avatar live />
      </div>
      <p className="me-10 text-xs text-muted">{label}</p>
    </div>
  );
}

export function useWaitLabel(busy: boolean, base: string): string {
  const [secs, setSecs] = useState(0);
  useEffect(() => {
    if (!busy) {
      setSecs(0);
      return;
    }
    const started = Date.now();
    const timer = window.setInterval(() => setSecs(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [busy]);
  if (secs >= 25) return "کند شده؛ هنوز منتظر جواب هستم…";
  if (secs >= 8) return "کمی طول می‌کشد؛ هنوز دارم کار می‌کنم…";
  return base;
}

/** پاسخ‌های سریع زیر یک سؤال: لمس می‌فرستد؛ فروشنده می‌تواند خودش هم بنویسد. */
export function QuickReplies({ options, disabled, onPick }: { options: string[]; disabled: boolean; onPick: (text: string) => void }) {
  return (
    <div className="mt-3" role="group" aria-label="پاسخ‌های پیشنهادی">
      <div className="flex flex-wrap gap-2">
        {options.map((option) => (
          <button
            key={option}
            type="button"
            disabled={disabled}
            onClick={() => onPick(option)}
            className="min-h-11 rounded-full border border-accent/40 bg-canvas px-4 text-[14px] text-ink shadow-sm transition active:scale-95 enabled:hover:border-accent enabled:hover:bg-accent/10 disabled:opacity-50"
          >
            {option}
          </button>
        ))}
      </div>
      <p className="mt-2 text-xs text-muted">یا جواب خودت را پایین بنویس.</p>
    </div>
  );
}

const CONFIRM_KIND: Record<string, { title: string; icon: typeof Hammer }> = {
  shop_chat: { title: "ساخت یا بازسازی فروشگاه", icon: Hammer },
  edit_shop: { title: "ویرایش فروشگاه", icon: PencilRuler },
  studio_chat: { title: "ساخت محتوا", icon: ImageIcon },
  publish_post: { title: "ارسال پست", icon: Megaphone },
  add_product: { title: "افزودن کالا", icon: Package },
  set_auto_reply: { title: "پاسخ خودکار دایرکت", icon: MessageSquareText },
  set_voice_tone: { title: "لحن پاسخ‌ها", icon: Sparkles },
};

/** کارتی که پیش از هر کار برگشت‌ناپذیر می‌آید: چه کاری، توضیح کوتاه، و دو دکمهٔ درشت. */
export function ConfirmCard({
  tool,
  text,
  open,
  busy,
  tapped,
  onConfirm,
  onCancel,
}: {
  tool?: string;
  text: string;
  open: boolean;
  busy: boolean;
  /** فروشنده همین حالا یکی از دکمه‌ها را لمس کرده و جواب هنوز نرسیده. */
  tapped?: "confirm" | "cancel";
  onConfirm: () => void;
  onCancel?: () => void;
}) {
  const spec = CONFIRM_KIND[tool || ""] || { title: "تأیید کار", icon: Check };
  const Icon = spec.icon;
  const live = open && !tapped;
  const head = tapped === "confirm" ? "در حال انجام…" : tapped === "cancel" ? "لغو شد" : open ? "منتظر تأیید توست" : "این کارت بسته شد";
  return (
    <div className={cn("overflow-hidden rounded-2xl border bg-canvas shadow-card transition-opacity", live ? "border-accent/50" : "border-line/70", !live && tapped !== "confirm" && "opacity-80")}>
      <div className={cn("flex items-center gap-3 border-b px-3.5 py-2.5", live || tapped === "confirm" ? "border-accent/20 bg-accent/10" : "border-line/60 bg-paper")}>
        <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-xl", live || tapped === "confirm" ? "bg-accentStrong text-onAccent" : "bg-line text-muted")}>
          <Icon size={18} aria-hidden />
        </span>
        <div className="min-w-0">
          <p className="text-[11px] text-warm" role={tapped ? "status" : undefined}>{head}</p>
          <p className="truncate text-[15px] font-bold text-ink">{spec.title}</p>
        </div>
      </div>
      <p className="wrap-any px-3.5 py-3 text-[15px] leading-[1.9] text-ink">{text}</p>
      {tapped === "confirm" ? <span aria-hidden className="sozan-shimmer block h-1" /> : null}
      {live ? (
        <div className="grid grid-cols-5 gap-2 px-3.5 pb-3.5">
          <Button type="button" className="col-span-3 gap-2" disabled={busy} onClick={onConfirm}>
            <Check size={18} aria-hidden />
            تأیید
          </Button>
          {onCancel ? (
            <Button type="button" variant="ghost" className="col-span-2" disabled={busy} onClick={onCancel}>
              انصراف
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/** یادداشت وضعیت بیلد در چت: در حال ساخت (نوار زنده)، آماده یا ناموفق. */
export function BuildNote({ text }: { text: string }) {
  const running = /^در حال ساخت|در حال طراحی|در حال /.test(text);
  const failed = !running && /کامل نشد|ناموفق|نشد/.test(text);
  return (
    <div className={cn("overflow-hidden rounded-2xl border bg-canvas shadow-card", failed ? "border-danger/40" : "border-accent/30")}>
      <div className="flex items-start gap-3 px-3.5 py-3">
        <span className={cn("mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl", failed ? "bg-danger/15 text-danger" : running ? "bg-accent/15 text-warm" : "bg-signal/20 text-signal")}>
          {failed ? <XCircle size={18} aria-hidden /> : running ? <Hammer size={18} aria-hidden className="sozan-hammer" /> : <CheckCircle2 size={18} aria-hidden />}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] text-warm">{running ? "فروشگاه در حال ساخت است" : failed ? "ساخت فروشگاه" : "فروشگاه"}</p>
          <p className="wrap-any text-[15px] leading-[1.9] text-ink">{text}</p>
        </div>
      </div>
      {running ? <span aria-hidden className="sozan-shimmer block h-1" /> : null}
      <Link href="/shop" className="flex min-h-11 items-center justify-center border-t border-line/60 text-sm font-medium text-warm hover:bg-paper">
        {running ? "دیدن مرحله‌ها در صفحهٔ فروشگاه" : "رفتن به فروشگاه"}
      </Link>
    </div>
  );
}

/** عکس یا ویدیویی که دارد ساخته می‌شود: همان جا که می‌آید یک قاب سایه‌ای زنده و متن مرحله. */
export function ComposePlaceholder({ label }: { label: string }) {
  return (
    <div className="mt-3 overflow-hidden rounded-2xl border border-line/70 bg-canvas" role="status">
      <div className="sozan-shimmer relative flex aspect-[4/3] max-h-60 w-full items-center justify-center">
        <Sparkles size={26} aria-hidden className="sozan-hammer text-warm" />
      </div>
      <p className="px-3.5 py-2.5 text-sm leading-7 text-warm">{label}</p>
    </div>
  );
}

export function SendIcon() {
  return <Send size={18} aria-hidden className="-scale-x-100" />;
}

export function Row({ children }: { children: ReactNode }) {
  return <div className="flex items-end gap-2">{children}</div>;
}

function composeWaitLabel(compose: { stage?: string; startedAt?: number }, now: number): string {
  const started = Number(compose.startedAt || 0);
  const elapsed = started > 0 ? Math.max(0, Math.round(now / 1000 - started)) : 0;
  const clock = elapsed ? ` ${elapsed.toLocaleString("fa-IR")} ثانیه گذشته.` : "";
  if (compose.stage === "layout") return `متن روی عکس چیده می‌شود. چند ثانیه.${clock}`;
  return `عکس در حال ساخته شدن است. معمولاً حدود یک دقیقه.${clock}`;
}

export function ComposeWait({ compose }: { compose: { stage?: string; startedAt?: number } }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return <ComposePlaceholder label={composeWaitLabel(compose, now)} />;
}

export function VoteButtons({ trainId }: { trainId: string }) {
  const [voted, setVoted] = useState<"" | "up" | "down">("");
  async function vote(good: boolean) {
    if (voted) return;
    setVoted(good ? "up" : "down");
    try {
      await api("/settings/feedback", { method: "POST", body: JSON.stringify({ trainId, good }) });
    } catch {
      setVoted("");
    }
  }
  return (
    <span className="flex items-center gap-1">
      <button
        type="button"
        aria-label="پاسخ خوب بود"
        disabled={voted !== ""}
        onClick={() => void vote(true)}
        className={cn("inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg px-2 text-base", voted === "up" ? "bg-accent/15 text-warm" : "text-muted hover:bg-canvas")}
      >
        👍
      </button>
      <button
        type="button"
        aria-label="پاسخ خوب نبود"
        disabled={voted !== ""}
        onClick={() => void vote(false)}
        className={cn("inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg px-2 text-base", voted === "down" ? "bg-accent/15 text-warm" : "text-muted hover:bg-canvas")}
      >
        👎
      </button>
    </span>
  );
}
