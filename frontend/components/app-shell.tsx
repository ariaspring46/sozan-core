"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Clapperboard, Inbox, MessageCircle, Menu, MoreHorizontal, ShoppingBag, Store, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { SozanMark } from "@/components/sozan-mark";
import { api } from "@/lib/api";
import { useAppViewport } from "@/lib/use-app-viewport";
import { useBackClose, useBackGuard } from "@/lib/back-stack";
import { usePlan } from "@/lib/use-plan";
import { formatQuota, useAiBudget } from "@/lib/use-ai-budget";
import { QuotaUsage } from "@/components/quota-usage";
import { applyTheme, readTheme } from "@/lib/theme";
import { ThemeToggle } from "@/components/theme-toggle";

type Tab = { href: string; label: string; icon: typeof MessageCircle };

/** همهٔ مقصدها: ستون ثابت دسکتاپ و منوی همبرگری موبایل. */
const TABS: readonly Tab[] = [
  { href: "/chat", label: "چت", icon: MessageCircle },
  { href: "/shop", label: "فروشگاه", icon: Store },
  { href: "/studio", label: "استودیو", icon: Clapperboard },
  { href: "/inbox", label: "صندوق", icon: Inbox },
  { href: "/sales", label: "فروش", icon: ShoppingBag },
  { href: "/more", label: "بیشتر", icon: MoreHorizontal },
];

function tabActive(pathname: string, href: string) {
  if (href === "/studio") {
    return pathname.startsWith("/studio") || pathname.startsWith("/campaigns");
  }
  if (href === "/sales") {
    return pathname === "/sales" || pathname.startsWith("/sales/");
  }
  if (href === "/more") {
    return pathname === "/more" || pathname.startsWith("/more/") || pathname.startsWith("/brand");
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** عنوان تب مرورگر برای هر بخش؛ در فهرست تب‌های گوشی معلوم باشد کدام صفحه است. */
const PAGE_TITLES: readonly [string, string][] = [
  ["/chat", "چت"],
  ["/shop", "فروشگاه"],
  ["/studio", "استودیو"],
  ["/campaigns", "کمپین‌ها"],
  ["/inbox", "صندوق"],
  ["/sales", "فروش"],
  ["/brand", "هویت و لوگو"],
  ["/more/inventory", "انبار"],
  ["/more/channels", "کانال‌ها"],
  ["/more/wallet", "کیف پول"],
  ["/more/settings", "پرداخت و پیامک"],
  ["/more/support", "پشتیبانی"],
  ["/more/docs", "اسناد آموزشی"],
  ["/more", "بیشتر"],
];

function unreadLabel(count: number) {
  if (count > 9) return "۹+";
  return count.toLocaleString("fa-IR");
}

function openPlansHere(pathname: string) {
  if (pathname !== "/more/settings") return;
  if (window.location.hash !== "#plans") window.location.hash = "plans";
  else window.dispatchEvent(new HashChangeEvent("hashchange"));
}

function Badge({ count }: { count: number }) {
  return (
    <span className="absolute -end-3 -top-2 inline-flex min-w-[20px] items-center justify-center rounded-full bg-accentStrong px-1 text-[11px] font-bold leading-5 text-onAccent">
      {unreadLabel(count)}
    </span>
  );
}

export function AppShell({
  children,
  header,
  scene = false,
}: {
  children: React.ReactNode;
  header?: React.ReactNode;
  /** صحنهٔ چت: زمینهٔ «درخشش مسی» زیر سربرگ شفاف و محتوا ادامه پیدا می‌کند. */
  scene?: boolean;
}) {
  const pathname = usePathname();
  const router = useRouter();
  useAppViewport();
  const [unread, setUnread] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const plan = usePlan();
  const aiBudget = useAiBudget();
  const exitHint = useBackGuard(() => router.replace("/chat"));
  useBackClose(menuOpen, () => setMenuOpen(false));

  useEffect(() => {
    const hit = PAGE_TITLES.find(([prefix]) => pathname === prefix || pathname.startsWith(`${prefix}/`));
    document.title = hit ? `${hit[1]} · سوزان` : "سوزان";
  }, [pathname]);

  // رنگ نوار مرورگر را با تم انتخابی هم‌راستا کن (اسکریپت head ممکن است قبل از متاها اجرا شده باشد).
  useEffect(() => {
    applyTheme(readTheme());
  }, []);

  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  // منوی موبایل: Escape می‌بندد، فوکوس داخل منو می‌رود و بعد از بستن به دکمهٔ منو برمی‌گردد.
  useEffect(() => {
    if (!menuOpen) return;
    closeButton.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", onKey);
    const opener = menuButton.current;
    return () => {
      window.removeEventListener("keydown", onKey);
      opener?.focus();
    };
  }, [menuOpen]);

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
    <div className={cn("sozan-app-shell flex w-full overflow-hidden", scene ? "sozan-chat" : "bg-canvas")}>
      <nav
        aria-label="ناوبری"
        className="hidden w-52 shrink-0 flex-col gap-1 border-e border-line bg-canvas/90 px-2 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 md:flex"
      >
        <div className="mb-3 flex items-center gap-2 px-2">
          <SozanMark className="h-9 w-9" />
          <span className="font-bold text-ink">سوزان</span>
        </div>
        {TABS.map((tab) => {
          const active = tabActive(pathname, tab.href);
          const Icon = tab.icon;
          return (
            <Link
              key={tab.href}
              href={tab.href}
              aria-current={active ? "page" : undefined}
              aria-label={label(tab)}
              className={cn(
                "relative flex min-h-11 items-center gap-3 rounded-xl px-3 py-2 text-sm",
                active ? "bg-accent/10 font-bold text-warm" : "text-muted hover:bg-paper/60 hover:text-ink",
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
          <Link href="/more/settings#plans" onClick={() => openPlansHere(pathname)} className="mt-2 block rounded-2xl border border-line bg-paper p-3 text-sm">
            <p className="text-xs text-muted">پلن فعلی</p>
            <p className="font-bold text-ink">{plan.label}</p>
            {aiBudget ? <p className="mt-1 text-xs text-muted">سهمیهٔ امروز {formatQuota(aiBudget.dailyPercent)}</p> : null}
            {plan.canUpgrade ? (
              <span className="mt-2 flex min-h-11 items-center justify-center rounded-xl bg-accentStrong px-3 text-xs font-bold text-onAccent mouse:min-h-9">
                ارتقای پلن
              </span>
            ) : null}
          </Link>
        ) : null}
      </nav>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col pb-[env(safe-area-inset-bottom,0px)]">
        <header className={cn("relative z-20 flex shrink-0 items-center gap-2 px-3 py-2.5 sm:px-4 sm:py-3", scene ? "bg-transparent" : "bg-paper/80 backdrop-blur-md")}>
          <button
            ref={menuButton}
            type="button"
            aria-label={unread > 0 ? `منو، ${unread} خوانده‌نشده` : "منو"}
            aria-haspopup="dialog"
            aria-expanded={menuOpen}
            aria-controls="app-menu"
            onClick={() => setMenuOpen(true)}
            className={cn("relative inline-flex h-11 w-11 shrink-0 items-center justify-center text-ink md:hidden", scene ? "sozan-glass rounded-full" : "rounded-xl hover:bg-canvas")}
          >
            <Menu size={24} aria-hidden />
            {unread > 0 ? <span aria-hidden className="absolute end-2 top-2 h-2.5 w-2.5 rounded-full bg-accentStrong ring-2 ring-paper" /> : null}
          </button>
          <div className="min-w-0 flex-1">{header}</div>
        </header>
        {aiBudget && aiBudget.tier !== "ok" ? (
          <div className="shrink-0 border-b border-line bg-paper px-4 py-2.5">
            <QuotaUsage budget={aiBudget} compact />
          </div>
        ) : null}
        <div className={cn("flex min-h-0 flex-1 flex-col overflow-hidden", !scene && "bg-paper")}>{children}</div>
      </div>

      {menuOpen ? (
        <div className="absolute inset-0 z-50 md:hidden">
          <button type="button" aria-label="بستن منو" tabIndex={-1} className="absolute inset-0 cursor-default bg-black/55 backdrop-blur-[2px]" onClick={() => setMenuOpen(false)} />
          <nav
            id="app-menu"
            role="dialog"
            aria-modal="true"
            aria-label="منوی سوزان"
            className="sozan-chat sozan-rise absolute inset-y-0 start-0 flex w-[min(19rem,86%)] flex-col gap-1 overflow-y-auto overscroll-contain border-e border-line/50 px-3 pb-[max(1rem,env(safe-area-inset-bottom))] pt-3 shadow-card"
          >
            <div className="mb-2 flex items-center justify-between gap-2 px-1">
              <span className="flex items-center gap-2">
                <SozanMark className="h-9 w-9" />
                <span className="font-bold text-ink">سوزان</span>
              </span>
              <button
                ref={closeButton}
                type="button"
                aria-label="بستن منو"
                onClick={() => setMenuOpen(false)}
                className="inline-flex h-11 w-11 items-center justify-center rounded-xl text-muted hover:bg-paper"
              >
                <X size={22} aria-hidden />
              </button>
            </div>
            {TABS.map((tab) => {
              const active = tabActive(pathname, tab.href);
              const Icon = tab.icon;
              return (
                <Link
                  key={tab.href}
                  href={tab.href}
                  aria-current={active ? "page" : undefined}
                  aria-label={label(tab)}
                  onClick={(event) => {
                    // همین صفحه: فقط منو بسته شود (رفتن دوباره به همین نشانی ورودی کهنه در تاریخچه می‌گذاشت).
                    if (pathname === tab.href) event.preventDefault();
                    setMenuOpen(false);
                  }}
                  className={cn(
                    "relative flex min-h-12 items-center gap-3 rounded-2xl px-3 text-[15px]",
                    active ? "sozan-glass font-bold text-warm" : "text-ink hover:bg-ink/5",
                  )}
                >
                  {active ? <span className="absolute inset-y-2 start-0 w-0.5 rounded-full bg-accent" /> : null}
                  <span className="relative">
                    <Icon size={22} strokeWidth={active ? 2.4 : 1.8} aria-hidden />
                    {tab.href === "/inbox" && unread > 0 ? <Badge count={unread} /> : null}
                  </span>
                  <span className="truncate">{tab.label}</span>
                </Link>
              );
            })}
            <ThemeToggle compact className="mt-auto" />
            {plan ? (
              <Link
                href="/more/settings#plans"
                onClick={() => {
                  setMenuOpen(false);
                  openPlansHere(pathname);
                }}
                className="mt-2 block rounded-2xl border border-line bg-paper p-3 text-sm"
              >
                <p className="text-xs text-muted">پلن فعلی</p>
                <p className="font-bold text-ink">{plan.label}</p>
                {aiBudget ? <p className="mt-1 text-xs text-muted">سهمیهٔ امروز {formatQuota(aiBudget.dailyPercent)}</p> : null}
                {plan.canUpgrade ? (
                  <span className="mt-2 flex min-h-11 items-center justify-center rounded-xl bg-accentStrong px-3 text-sm font-bold text-onAccent">
                    ارتقای پلن
                  </span>
                ) : null}
              </Link>
            ) : null}
          </nav>
        </div>
      ) : null}

      <div aria-live="polite" className="pointer-events-none absolute inset-x-0 bottom-[calc(env(safe-area-inset-bottom,0px)+6.5rem)] z-[60] flex justify-center px-4">
        {exitHint ? <p className="sozan-glass sozan-rise rounded-full px-4 py-2.5 text-sm font-medium text-ink shadow-card">برای خروج، دوباره «برگشت» را بزن</p> : null}
      </div>
    </div>
  );
}
