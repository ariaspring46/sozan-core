"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { Clapperboard, Inbox, MessageCircle, MoreHorizontal, ShoppingBag, Store } from "lucide-react";
import { cn } from "@/lib/utils";
import { SozanMark } from "@/components/sozan-mark";
import { api } from "@/lib/api";
import { useAppViewport } from "@/lib/use-app-viewport";
import { usePlan } from "@/lib/use-plan";
import { useAiBudget } from "@/lib/use-ai-budget";
import { applyTheme, readTheme } from "@/lib/theme";
import { ThemeToggle } from "@/components/theme-toggle";

type Tab = { href: string; label: string; icon: typeof MessageCircle };

/** ستون ثابت دسکتاپ: همهٔ مقصدها. */
const TABS: readonly Tab[] = [
  { href: "/chat", label: "چت", icon: MessageCircle },
  { href: "/shop", label: "فروشگاه", icon: Store },
  { href: "/studio", label: "استودیو", icon: Clapperboard },
  { href: "/inbox", label: "صندوق", icon: Inbox },
  { href: "/sales", label: "فروش", icon: ShoppingBag },
  { href: "/more", label: "بیشتر", icon: MoreHorizontal },
];

/** نوار پایین موبایل: پنج مقصد اصلی؛ استودیو از «بیشتر» و چت در دسترس است. */
const MOBILE_TABS: readonly Tab[] = TABS.filter((tab) => tab.href !== "/studio");

function tabActive(pathname: string, href: string, mobile: boolean) {
  if (href === "/studio") {
    return pathname.startsWith("/studio") || pathname.startsWith("/campaigns");
  }
  if (href === "/sales") {
    return pathname === "/sales" || pathname.startsWith("/sales/");
  }
  if (href === "/more") {
    const inMore = pathname === "/more" || pathname.startsWith("/more/") || pathname.startsWith("/brand");
    const studio = pathname.startsWith("/studio") || pathname.startsWith("/campaigns");
    return inMore || (mobile && studio);
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

function unreadLabel(count: number) {
  if (count > 9) return "۹+";
  return count.toLocaleString("fa-IR");
}

function Badge({ count }: { count: number }) {
  return (
    <span className="absolute -end-2.5 -top-1.5 inline-flex min-w-[18px] items-center justify-center rounded-full bg-accentStrong px-1 text-[10px] font-bold leading-[18px] text-onAccent">
      {unreadLabel(count)}
    </span>
  );
}

export function AppShell({
  children,
  header,
}: {
  children: React.ReactNode;
  header?: React.ReactNode;
}) {
  const pathname = usePathname();
  useAppViewport();
  const [unread, setUnread] = useState(0);
  const [typing, setTyping] = useState(false);
  const plan = usePlan();
  const aiBudget = useAiBudget();

  // رنگ نوار مرورگر را با تم انتخابی هم‌راستا کن (اسکریپت head ممکن است قبل از متاها اجرا شده باشد).
  useEffect(() => {
    applyTheme(readTheme());
  }, []);

  // وقتی کیبورد موبایل باز است، نوار پایین جا را از فیلد نوشتن نگیرد.
  useEffect(() => {
    const isField = (el: EventTarget | null) =>
      el instanceof HTMLElement && (el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && !["checkbox", "radio", "file", "button", "submit"].includes((el as HTMLInputElement).type)) || el.isContentEditable);
    const onIn = (event: FocusEvent) => setTyping(isField(event.target));
    const onOut = () => window.setTimeout(() => setTyping(isField(document.activeElement)), 0);
    document.addEventListener("focusin", onIn);
    document.addEventListener("focusout", onOut);
    return () => {
      document.removeEventListener("focusin", onIn);
      document.removeEventListener("focusout", onOut);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      if (typeof document !== "undefined" && document.hidden) return;
      void api<{ count: number }>("/inbox/unread")
        .then((data) => {
          if (!cancelled) setUnread(Number(data.count) || 0);
        })
        .catch(() => undefined);
    };
    tick();
    const timer = window.setInterval(tick, 15000);
    const onVis = () => {
      if (!document.hidden) tick();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [pathname]);

  const label = (tab: Tab) => (tab.href === "/inbox" && unread > 0 ? `${tab.label}، ${unread} خوانده‌نشده` : tab.label);

  return (
    <div className="sozan-app-shell flex w-full overflow-hidden bg-canvas">
      <nav
        aria-label="ناوبری"
        className="hidden w-52 shrink-0 flex-col gap-1 border-e border-line bg-canvas px-2 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 md:flex"
      >
        <div className="mb-3 flex items-center gap-2 px-2">
          <SozanMark className="h-9 w-9" />
          <span className="font-bold text-ink">سوزان</span>
        </div>
        {TABS.map((tab) => {
          const active = tabActive(pathname, tab.href, false);
          const Icon = tab.icon;
          return (
            <Link
              key={tab.href}
              href={tab.href}
              aria-current={active ? "page" : undefined}
              aria-label={label(tab)}
              className={cn(
                "relative flex min-h-11 items-center gap-3 rounded-xl px-3 py-2 text-sm",
                active ? "bg-paper font-bold text-warm" : "text-muted hover:bg-paper/60 hover:text-ink",
              )}
            >
              {active ? <span className="absolute inset-y-2 start-0 w-0.5 rounded-full bg-accent" /> : null}
              <span className="relative">
                <Icon size={20} strokeWidth={active ? 2.4 : 1.8} />
                {tab.href === "/inbox" && unread > 0 ? <Badge count={unread} /> : null}
              </span>
              <span className="truncate">{tab.label}</span>
            </Link>
          );
        })}
        <ThemeToggle compact className="mt-auto" />
        {plan ? (
          <div className="mt-2 rounded-2xl border border-line bg-paper p-3 text-sm">
            <p className="text-xs text-muted">پلن فعلی</p>
            <p className="font-bold text-ink">{plan.label}</p>
            {plan.canUpgrade ? (
              <Link href="/more/settings#plans" className="mt-2 flex min-h-9 items-center justify-center rounded-xl bg-accentStrong px-3 text-xs font-bold text-onAccent">
                ارتقای پلن
              </Link>
            ) : null}
          </div>
        ) : null}
      </nav>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col md:pb-[env(safe-area-inset-bottom,0px)]">
        <header className="relative z-20 flex shrink-0 items-center gap-3 bg-paper/80 px-3 py-2.5 backdrop-blur-md sm:px-4 sm:py-3">
          <SozanMark className="h-9 w-9 shrink-0 md:hidden" />
          <div className="min-w-0 flex-1">{header}</div>
        </header>
        {aiBudget && aiBudget.tier !== "ok" && aiBudget.note ? (
          <div className="flex shrink-0 items-center justify-between gap-3 border-b border-line bg-paper px-4 py-2 text-xs text-warm">
            <span className="min-w-0">{aiBudget.note}</span>
            {aiBudget.tier === "capped" ? (
              <Link href="/more/settings" className="shrink-0 rounded-lg bg-accentStrong px-3 py-1 font-bold text-onAccent">
                ارتقای پلن
              </Link>
            ) : null}
          </div>
        ) : null}
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-paper">{children}</div>
        <nav
          aria-label="ناوبری"
          className={cn(
            "shrink-0 border-t border-line bg-canvas pb-[env(safe-area-inset-bottom,0px)] md:hidden",
            typing ? "hidden" : "flex",
          )}
        >
          {MOBILE_TABS.map((tab) => {
            const active = tabActive(pathname, tab.href, true);
            const Icon = tab.icon;
            return (
              <Link
                key={tab.href}
                href={tab.href}
                aria-current={active ? "page" : undefined}
                aria-label={label(tab)}
                className={cn(
                  "flex min-h-14 flex-1 flex-col items-center justify-center gap-1 text-[11px]",
                  active ? "font-bold text-warm" : "text-muted",
                )}
              >
                <span className="relative">
                  <Icon size={22} strokeWidth={active ? 2.4 : 1.8} />
                  {tab.href === "/inbox" && unread > 0 ? <Badge count={unread} /> : null}
                </span>
                <span>{tab.label}</span>
              </Link>
            );
          })}
        </nav>
      </div>
    </div>
  );
}
