"use client";

import Link from "next/link";

const LINKS = [
  { href: "/chat", label: "گفتگو" },
  { href: "/shop", label: "ویترین" },
  { href: "/studio", label: "استودیو" },
  { href: "/inbox", label: "صندوق" },
] as const;

export function ChatNav({ current }: { current: "chat" | "shop" | "studio" | "inbox" }) {
  return (
    <nav className="flex flex-wrap items-center gap-3 text-sm">
      {LINKS.map((item) => {
        const active =
          (current === "chat" && item.href === "/chat") ||
          (current === "shop" && item.href === "/shop") ||
          (current === "studio" && item.href === "/studio") ||
          (current === "inbox" && item.href === "/inbox");
        return (
          <Link
            key={item.href}
            href={item.href}
            className={active ? "font-bold text-ink" : "text-muted"}
            aria-current={active ? "page" : undefined}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
