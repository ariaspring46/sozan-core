"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { Clapperboard, Inbox, MessageCircle, MoreHorizontal, ShoppingBag, Store } from "lucide-react";
import { cn } from "@/lib/utils";
import { SozanMark } from "@/components/sozan-mark";
import { api } from "@/lib/api";
import { useAppViewport } from "@/lib/use-app-viewport";

const TABS = [
  { href: "/chat", label: "چت", icon: MessageCircle },
  { href: "/shop", label: "فروشگاه", icon: Store },
  { href: "/studio", label: "استودیو", icon: Clapperboard },
  { href: "/inbox", label: "صندوق", icon: Inbox },
  { href: "/sales", label: "فروش", icon: ShoppingBag },
  { href: "/more", label: "بیشتر", icon: MoreHorizontal },
] as const;

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

function unreadLabel(count: number) {
  if (count > 9) return "۹+";
  return count.toLocaleString("fa-IR");
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
    const timer = window.setInterval(tick, 4000);
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

  return (
    <div className="sozan-app-shell flex w-full overflow-hidden bg-canvas">
      <nav
        aria-label="ناوبری"
        className="z-40 flex w-14 shrink-0 flex-col gap-1 border-e border-line bg-canvas px-1.5 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-[max(0.75rem,env(safe-area-inset-top))] md:w-44 md:px-2"
      >
        {TABS.map((tab) => {
          const active = tabActive(pathname, tab.href);
          const Icon = tab.icon;
          const badge = tab.href === "/inbox" && unread > 0;
          return (
            <Link
              key={tab.href}
              href={tab.href}
              aria-current={active ? "page" : undefined}
              aria-label={badge ? `${tab.label}، ${unread} خوانده‌نشده` : tab.label}
              className={cn(
                "relative flex min-h-11 items-center justify-center gap-2 rounded-xl px-1 py-2 text-sm md:justify-start md:px-3",
                active ? "bg-paper text-warm" : "text-muted",
              )}
            >
              {active ? <span className="absolute inset-y-2 start-0 w-0.5 rounded-full bg-accent" /> : null}
              <span className="relative">
                <Icon size={20} strokeWidth={active ? 2.4 : 1.8} />
                {badge ? (
                  <span className="absolute -end-2 -top-1 inline-flex min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[9px] text-onAccent">
                    {unreadLabel(unread)}
                  </span>
                ) : null}
              </span>
              <span className="hidden truncate md:inline">{tab.label}</span>
            </Link>
          );
        })}
      </nav>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col pb-[env(safe-area-inset-bottom,0px)]">
        {header ? (
          <header className="relative z-20 flex shrink-0 items-center gap-3 bg-paper/80 px-3 py-2.5 backdrop-blur-md sm:px-4 sm:py-3">
            <SozanMark className="h-9 w-9 shrink-0 sm:h-10 sm:w-10" />
            <div className="min-w-0 flex-1">{header}</div>
          </header>
        ) : null}
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-paper">{children}</div>
      </div>
    </div>
  );
}
