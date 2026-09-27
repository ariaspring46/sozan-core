"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Check } from "lucide-react";
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

  return (
    <section aria-label="شروع کار" className="mx-3 mt-3 rounded-2xl border border-accent/30 bg-canvas p-4 shadow-card sm:mx-4">
      <div className="flex items-center justify-between gap-2">
        <button type="button" className="flex min-h-9 items-center gap-2 font-bold" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
          شروع کار
          <span className="text-xs font-normal text-warm">{open ? "کمتر" : "همه"}</span>
        </button>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted">
            {doneCount.toLocaleString("fa-IR")} از {steps.length.toLocaleString("fa-IR")}
          </span>
          <button
            type="button"
            className="min-h-9 px-1 text-xs text-muted"
            onClick={() => {
              try {
                localStorage.setItem(HIDE_KEY, "1");
              } catch {
                /* ignore */
              }
              setHidden(true);
            }}
          >
            بستن
          </button>
        </div>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-line" aria-hidden>
        <div className="h-full rounded-full bg-warm" style={{ width: `${(doneCount / steps.length) * 100}%` }} />
      </div>
      {!open && next ? (
        <Link href={next.href} className="mt-3 flex min-h-11 items-center justify-between gap-3 rounded-xl bg-paper px-3 py-2 text-sm">
          <span className="min-w-0">
            <span className="block text-xs text-muted">قدم بعد</span>
            <span className="block truncate font-medium text-ink">{next.title}</span>
          </span>
          <span className="shrink-0 text-warm">انجام بده</span>
        </Link>
      ) : null}
      {open ? (
      <ol className="mt-3 space-y-1">
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
