"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Check, ChevronDown, X } from "lucide-react";
import { api } from "@/lib/api";

type Step = { id: string; title: string; hint: string; href: string; done: boolean };

const HIDE_KEY = "sozan_start_hidden";

function readHidden(): boolean {
  try {
    return localStorage.getItem(HIDE_KEY) === "1";
  } catch {
    return false;
  }
}

/** فهرست «شروع کار» برای فروشندهٔ تازه؛ وقتی همه انجام شد یا بسته شد، دیده نمی‌شود. */
export function GettingStarted() {
  const [steps, setSteps] = useState<Step[] | null>(null);
  const [hidden, setHidden] = useState(true);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setHidden(readHidden());
    let cancelled = false;
    void Promise.all([
      api<{ accounts?: { connected?: boolean; needsReconnect?: boolean }[] }>("/channels").catch(() => ({ accounts: [] })),
      api<{ products?: { price?: number }[] }>("/catalog").catch(() => ({ products: [] })),
      api<{ shop?: { status?: string; publicHost?: string; url?: string } }>("/shop").catch(() => ({ shop: undefined })),
      api<unknown[]>("/campaigns").catch(() => [] as unknown[]),
      api<{ autoReply?: string }>("/inbox?status=unread").catch(() => ({ autoReply: "" })),
      api<Record<string, string | number>>("/settings/sales-policy").catch(() => ({}) as Record<string, string | number>),
    ]).then(([channels, catalog, shop, campaigns, inbox, policy]) => {
      if (cancelled) return;
      const products = catalog.products || [];
      const priced = products.filter((row) => Number(row.price) > 0).length;
      const siteReady = Boolean(shop.shop && (shop.shop.status === "ready" || shop.shop.publicHost || shop.shop.url));
      setSteps([
        {
          id: "channel",
          title: "اتصال اینستاگرام یا تلگرام",
          hint: "تا دایرکت مشتری‌ها به صندوق بیاید.",
          href: "/more/channels",
          done: (channels.accounts || []).some((row) => row.connected && !row.needsReconnect),
        },
        {
          id: "prices",
          title: "کالاها با قیمت واقعی",
          hint: products.length ? `${priced.toLocaleString("fa-IR")} از ${products.length.toLocaleString("fa-IR")} کالا قیمت دارد.` : "کالا اضافه کن یا از صفحهٔ اینستاگرامت بخوان.",
          href: "/more/inventory",
          done: products.length > 0 && priced === products.length,
        },
        {
          id: "site",
          title: "ساختن سایت فروشگاه",
          hint: "در تب فروشگاه بگو چه حسی می‌خواهی و بساز.",
          href: "/shop",
          done: siteReady,
        },
        {
          id: "post",
          title: "اولین پست",
          hint: "در همین چت بگو برای کدام کالا پست بسازم.",
          href: "/chat",
          done: Array.isArray(campaigns) && campaigns.length > 0,
        },
        {
          id: "policy",
          title: "ارسال و مرجوعی",
          hint: "هزینه، زمان، شهرها و شرط مرجوعی را بنویس تا دایرکت خودش جواب بدهد.",
          href: "/more/settings#shipping",
          done: Boolean(policy.shippingMethod || policy.shippingDays || policy.returnNote),
        },
        {
          id: "auto",
          title: "روشن کردن پاسخ به دایرکت",
          hint: "پیش‌نویس یا ارسال خودکار، در صندوق.",
          href: "/inbox",
          done: Boolean(inbox.autoReply),
        },
      ]);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (hidden || !steps) return null;
  const doneCount = steps.filter((step) => step.done).length;
  if (doneCount === steps.length) return null;
  const next = steps.find((step) => !step.done);

  const hide = () => {
    try {
      localStorage.setItem(HIDE_KEY, "1");
    } catch {
      /* ignore */
    }
    setHidden(true);
  };

  return (
    <section aria-label="شروع کار" className="sozan-glass mx-3 mt-1 shrink-0 overflow-hidden rounded-2xl sm:mx-4">
      <div className="flex items-center gap-1 px-1.5 py-1">
        {next ? (
          <Link href={next.href} className="flex min-h-11 min-w-0 flex-1 items-center gap-3 rounded-xl px-2.5 hover:bg-paper">
            <span className="shrink-0 rounded-full bg-accent/15 px-2 py-0.5 text-xs text-warm">
              {doneCount.toLocaleString("fa-IR")} از {steps.length.toLocaleString("fa-IR")}
            </span>
            <span className="min-w-0">
              <span className="block text-xs text-muted">قدم بعد</span>
              <span className="block truncate text-sm font-medium text-ink">{next.title}</span>
            </span>
          </Link>
        ) : null}
        <button
          type="button"
          className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-muted hover:bg-paper"
          aria-expanded={open}
          aria-label={open ? "بستن فهرست قدم‌ها" : "نمایش همهٔ قدم‌ها"}
          onClick={() => setOpen((value) => !value)}
        >
          <ChevronDown size={18} className={open ? "rotate-180" : undefined} aria-hidden />
        </button>
        <button type="button" className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-muted hover:bg-paper" aria-label="پنهان کردن شروع کار" onClick={hide}>
          <X size={18} aria-hidden />
        </button>
      </div>
      <div className="h-[3px] bg-line/40" aria-hidden>
        <div className="h-full rounded-full bg-gradient-to-l from-accent to-warm" style={{ width: `${(doneCount / steps.length) * 100}%` }} />
      </div>
      {open ? (
        <ol className="space-y-1 p-2">
          {steps.map((step) => (
            <li key={step.id}>
              <Link href={step.href} className="flex min-h-11 items-center gap-3 rounded-xl px-2 py-1.5 hover:bg-paper">
                <span
                  className={
                    step.done
                      ? "flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-signal text-canvas"
                      : "h-6 w-6 shrink-0 rounded-full border-2 border-field"
                  }
                  aria-hidden
                >
                  {step.done ? <Check size={14} strokeWidth={3} /> : null}
                </span>
                <span className="min-w-0">
                  <span className={step.done ? "block text-sm text-muted line-through" : "block text-sm font-medium text-ink"}>{step.title}</span>
                  {!step.done ? <span className="block text-xs text-muted">{step.hint}</span> : null}
                </span>
                <span className="sr-only">{step.done ? "انجام شد" : "انجام نشده"}</span>
              </Link>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}
