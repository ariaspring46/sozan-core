"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { Clapperboard, MessageCircle, MoreHorizontal, ShoppingBag, Store } from "lucide-react";
import { cn } from "@/lib/utils";
import { SozanMark } from "@/components/sozan-mark";
import { api } from "@/lib/api";
import { useAppViewport } from "@/lib/use-app-viewport";

const TABS = [
  { href: "/shop", label: "فروشگاه", icon: Store },
  { href: "/studio", label: "استودیو", icon: Clapperboard },
  { href: "/inbox", label: "چت", icon: MessageCircle },
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

export function AppShell({
  children,
  header,
}: {
  children: React.ReactNode;
  header?: React.ReactNode;
}) {
  const pathname = usePathname();
  const keyboardOpen = useAppViewport();
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
    <div className="sozan-app-shell flex w-full flex-col overflow-hidden bg-canvas">
      <div className="mx-auto flex min-h-0 w-full flex-1 flex-col">
        {header ? (
          <header className="relative z-20 flex shrink-0 items-center gap-3 bg-paper/80 px-3 py-2.5 backdrop-blur-md sm:px-4 sm:py-3">
            <SozanMark className="h-9 w-9 shrink-0 sm:h-10 sm:w-10" />
            <div className="min-w-0 flex-1">{header}</div>
          </header>
        ) : null}
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-paper">{children}</div>
      </div>
      <nav
        className={cn(
          "z-40 shrink-0 border-t border-line bg-canvas pb-[env(safe-area-inset-bottom,0px)]",
          keyboardOpen && "hidden",
        )}
      >
        <div className="grid grid-cols-5">
          {TABS.map((tab) => {
            const active = tabActive(pathname, tab.href);
            const Icon = tab.icon;
            return (
              <Link
                key={tab.href}
                href={tab.href}
                aria-label={tab.href === "/inbox" && unread ? `${tab.label}، ${unread} خوانده‌نشده` : tab.label}
                className={cn(
                  "relative flex min-h-[3.25rem] flex-col items-center justify-center gap-0.5 px-1 py-1.5 text-[11px] leading-tight",
                  active ? "text-warm" : "text-muted",
                )}
              >
                <span className="relative">
                  <Icon size={20} strokeWidth={active ? 2.4 : 1.8} />
                  {tab.href === "/inbox" && unread > 0 ? (
                    <span className="absolute -end-2 -top-1 inline-flex min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[9px] text-onAccent">
                      {unread > 9 ? "۹+" : unread}
                    </span>
                  ) : null}
                </span>
                {tab.label}
                {active ? <span className="mt-0.5 h-1 w-1 rounded-full bg-accent" /> : <span className="mt-0.5 h-1 w-1" />}
              </Link>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
