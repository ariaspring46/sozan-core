"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";

const TABS = [
  { id: "studio", href: "/studio", label: "محتوا" },
  { id: "campaigns", href: "/campaigns", label: "کمپین‌ها" },
] as const;

export function StudioNav({ current }: { current: "studio" | "campaigns" }) {
  return (
    <nav aria-label="بخش‌های استودیو" className="flex items-center gap-2 text-sm">
      {TABS.map((tab) => {
        const active = current === tab.id;
        return (
          <Link
            key={tab.id}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "inline-flex min-h-11 items-center rounded-xl px-4",
              active ? "bg-canvas font-bold text-ink shadow-card" : "text-muted hover:bg-canvas/60",
            )}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
