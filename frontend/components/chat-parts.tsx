"use client";

import { ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import Link from "next/link";
import { Check, CheckCircle2, Hammer, ImageIcon, Megaphone, MessageSquareText, Package, PencilRuler, Send, Sparkles, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { SozanOrb } from "@/components/sozan-orb";

/** ساعت پیام: امروز فقط ساعت، قدیمی‌تر روز و ساعت. */
export function shortWhen(at: number): string {
  if (!at) return "";
  const date = new Date(at * 1000);
  const now = new Date();
  const time = date.toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit" });
  if (date.toDateString() === now.toDateString()) return time;
  return `${date.toLocaleDateString("fa-IR", { day: "numeric", month: "long" })}، ${time}`;
}

/** آواتار سوزان کنار حباب: همان گوی سوزان، کوچک و ساکن (یک بار کشیده می‌شود). */
export function Avatar() {
  return (
    <span className="relative mb-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center">
      <SozanOrb size={34} still />
    </span>
  );
}

/** جای خالی هم‌عرضِ آواتار تا حباب‌های پشت‌سرهم یک‌خط بمانند. */
export function AvatarSpacer() {
  return <span aria-hidden className="inline-block h-8 w-8 shrink-0" />;
}

/**
 * وقتی مدل دارد می‌نویسد: همان‌جا که جواب می‌آید (سمت سوزان) گوی سوزان تند می‌چرخد و کنارش متن درخشانی می‌گوید چه می‌کند.
 * هر چه انتظار طولانی‌تر شود متن صادقانه‌تر می‌شود تا کاربر فکر نکند برنامه قفل کرده.
 */
export function TypingBubble({ label }: { label: string }) {
  return (
    <div className="ms-auto flex w-fit max-w-[90%] items-center gap-2" role="status" aria-live="polite" data-typing>
      <span className="sozan-ai rounded-full px-4 py-2.5">
        <span className="sozan-shine text-[14px] font-medium">{label}</span>
      </span>
      <span className="relative shrink-0">
        <span aria-hidden className="sozan-halo absolute -inset-3 rounded-full" />
        <SozanOrb size={44} busy className="relative" />
      </span>
    </div>
  );
}

/**
 * متن جواب تازهٔ سوزان مثل نوشته‌شدن زنده می‌آید: حباب از یک خط تا اندازهٔ کامل بزرگ می‌شود (زمان به نسبت طول متن)،
 * خط آخر در لبه محو است و هر چه زیر متن است (پاسخ‌های سریع، کپشن) درست وقتی نوشتن تمام شد بالا می‌آید.
 * متن از اول کامل در صفحه است (صفحه‌خوان).
 */
export function RevealText({ on, className, children }: { on: boolean; className?: string; children: ReactNode }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const played = useRef(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!on || played.current || !el || typeof el.animate !== "function") return;
    played.current = true;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const full = el.scrollHeight;
    const line = parseFloat(getComputedStyle(el).lineHeight) || 28;
    if (full <= line * 1.5) return;
    const ms = Math.round(Math.min(2400, (full / line) * 340));
    const below: HTMLElement[] = [];
    for (let node = el.nextElementSibling; node; node = node.nextElementSibling) below.push(node as HTMLElement);
    below.forEach((node) => (node.style.display = "none"));
    el.classList.add("sozan-writing");
    const run = el.animate([{ height: `${line}px` }, { height: `${full}px` }], { duration: ms, easing: "cubic-bezier(0.3, 0.5, 0.45, 1)" });
    run.onfinish = run.oncancel = () => {
      el.classList.remove("sozan-writing");
      below.forEach((node) => {
        node.style.display = "";
        node.animate([{ opacity: 0, transform: "translateY(8px)" }, { opacity: 1, transform: "none" }], { duration: 380, easing: "cubic-bezier(0.2, 0.7, 0.2, 1)" });
      });
    };
  }, [on]);
  return (
    <p ref={ref} className={cn(className, on && "sozan-reveal")}>
      {children}
    </p>
  );
}

/**
 * پیام‌هایی که بعد از باز شدن گفتگو رسیده‌اند (نه تاریخچه): فقط این‌ها با نوشته‌شدن تدریجی نشان داده می‌شوند.
 * رسیدن یک‌بارهٔ چند پیام (عوض کردن گفتگو) تاریخچه حساب می‌شود.
 */
export function useFreshIds(ids: string[], ready: boolean): Set<string> {
  const known = useRef<Set<string> | null>(null);
  const fresh = useRef(new Set<string>());
  if (ready && !known.current) known.current = new Set(ids);
  if (known.current) {
    const added = ids.filter((id) => !known.current?.has(id));
    added.forEach((id) => known.current?.add(id));
    if (added.length <= 3) added.forEach((id) => fresh.current.add(id));
  }
  return fresh.current;
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
  if (secs >= 3) return "دارم جواب را می‌چینم…";
  return base;
}

/** پاسخ‌های سریع زیر یک سؤال: لمس می‌فرستد؛ فروشنده می‌تواند خودش هم بنویسد. */
export function QuickReplies({ options, disabled, onPick }: { options: string[]; disabled: boolean; onPick: (text: string) => void }) {
  return (
    <div className="mt-3" role="group" aria-label="پاسخ‌های پیشنهادی">
      <div className="flex flex-wrap gap-2">
        {options.map((option, index) => (
          <button
            key={option}
            type="button"
            disabled={disabled}
            style={{ animationDelay: `${200 + index * 60}ms` }}
            onClick={() => onPick(option)}
            className="sozan-rise min-h-11 rounded-full border border-accent/45 bg-accent/10 px-4 text-[14px] font-medium text-ink backdrop-blur transition active:scale-95 enabled:hover:border-accent enabled:hover:bg-accent/20 disabled:opacity-50"
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
    <div className={cn("overflow-hidden rounded-[1.4rem] transition-opacity", live ? "sozan-card" : "sozan-ai", !live && tapped !== "confirm" && "opacity-80")}>
      <div className={cn("flex items-center gap-3 border-b px-4 py-3", live || tapped === "confirm" ? "border-accent/20 bg-accent/10" : "border-line/40")}>
        <span className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl", live || tapped === "confirm" ? "sozan-tile" : "bg-line/60 text-muted")}>
          <Icon size={18} aria-hidden />
        </span>
        <div className="min-w-0">
          <p className="text-[11px] text-warm" role={tapped ? "status" : undefined}>{head}</p>
          <p className="truncate text-[15px] font-bold text-ink">{spec.title}</p>
        </div>
      </div>
      <p className="wrap-any px-4 py-3 text-[15px] leading-[1.9] text-ink">{text}</p>
      {tapped === "confirm" ? <span aria-hidden className="sozan-shimmer block h-1" /> : null}
      {live ? (
        <div className="grid grid-cols-5 gap-2 px-4 pb-4">
          <Button type="button" className="sozan-send col-span-3 gap-2 rounded-2xl" disabled={busy} onClick={onConfirm}>
            <Check size={18} aria-hidden />
            تأیید
          </Button>
          {onCancel ? (
            <Button type="button" variant="ghost" className="col-span-2 rounded-2xl border-line/60 bg-transparent" disabled={busy} onClick={onCancel}>
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
    <div className={cn("overflow-hidden rounded-[1.4rem]", failed ? "sozan-ai border-danger/40" : "sozan-card")}>
      <div className="flex items-start gap-3 px-4 py-3">
        <span className={cn("mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl", failed ? "bg-danger/15 text-danger" : running ? "sozan-tile" : "bg-signal/20 text-signal")}>
          {failed ? <XCircle size={18} aria-hidden /> : running ? <Hammer size={18} aria-hidden className="sozan-hammer" /> : <CheckCircle2 size={18} aria-hidden />}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] text-warm">{running ? "فروشگاه در حال ساخت است" : failed ? "ساخت فروشگاه" : "فروشگاه"}</p>
          <p className="wrap-any text-[15px] leading-[1.9] text-ink">{text}</p>
        </div>
      </div>
      {running ? <span aria-hidden className="sozan-shimmer block h-1" /> : null}
      <Link href="/shop" className="flex min-h-11 items-center justify-center border-t border-line/40 text-sm font-medium text-warm hover:bg-accent/10">
        {running ? "دیدن مرحله‌ها در صفحهٔ فروشگاه" : "رفتن به فروشگاه"}
      </Link>
    </div>
  );
}

/** عکس یا ویدیویی که دارد ساخته می‌شود: همان جا که می‌آید یک قاب سایه‌ای زنده و متن مرحله. */
export function ComposePlaceholder({ label }: { label: string }) {
  return (
    <div className="sozan-card mt-3 overflow-hidden rounded-2xl" role="status">
      <div className="sozan-shimmer relative flex aspect-[4/3] max-h-60 w-full items-center justify-center">
        <SozanOrb size={96} busy />
      </div>
      <p className="px-4 py-2.5 text-sm leading-7 text-warm">{label}</p>
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
