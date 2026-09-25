"use client";

import Link from "next/link";

export function StudioNav({ current }: { current: "studio" | "campaigns" }) {
  return (
    <nav className="flex items-center gap-4 text-sm">
      <Link href="/studio" className={current === "studio" ? "font-bold text-ink" : "text-muted"} aria-current={current === "studio" ? "page" : undefined}>
        محتوا
      </Link>
      <Link
        href="/campaigns"
        className={current === "campaigns" ? "font-bold text-ink" : "text-muted"}
        aria-current={current === "campaigns" ? "page" : undefined}
      >
        کمپین‌ها
      </Link>
    </nav>
  );
}
