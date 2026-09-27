"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { Field } from "@/components/field";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { api } from "@/lib/api";
import { formatWhen, money, parseNonNegativeInt } from "@/lib/digits";
import { EmptyState } from "@/components/empty-state";

type Sale = {
  id: string;
  title: string;
  amount: number;
  customer: string;
  channel: string;
  status: string;
  at: number;
};

type Order = { id: string; title: string; amount: number; status: string; channel: string; payUrl?: string };

type Account = { id: string; label: string; handle: string };

const SHOP_CHANNEL = "فروشگاه";
const DAY = 24 * 60 * 60;

function isPaid(sale: Sale) {
  return !sale.status || sale.status === "paid";
}

function sumSince(rows: Sale[], since: number) {
  return rows.filter((row) => isPaid(row) && (row.at || 0) >= since).reduce((acc, row) => acc + (row.amount || 0), 0);
}

export default function SalesPage() {
  const [sales, setSales] = useState<Sale[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [channels, setChannels] = useState<string[]>([SHOP_CHANNEL]);
  const [title, setTitle] = useState("");
  const [amount, setAmount] = useState("");
  const [customer, setCustomer] = useState("");
  const [channel, setChannel] = useState(SHOP_CHANNEL);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [formOpen, setFormOpen] = useState(false);

  async function load() {
    const [saleData, channelData, orderData] = await Promise.all([
      api<{ sales: Sale[] }>("/sales"),
      api<{ accounts: Account[] }>("/channels").catch(() => ({ accounts: [] as Account[] })),
      api<{ orders: Order[] }>("/wallet/orders").catch(() => ({ orders: [] as Order[] })),
    ]);
    setSales(saleData.sales || []);
    setOrders(orderData.orders || []);
    const connected = (channelData.accounts || []).map((item) => item.label).filter(Boolean);
    setChannels([SHOP_CHANNEL, ...connected.filter((item, index, all) => item !== SHOP_CHANNEL && all.indexOf(item) === index)]);
  }

  useEffect(() => {
    void load()
      .catch((err) => setError(err instanceof Error ? err.message : "خواندن فروش‌ها انجام نشد."))
      .finally(() => setLoading(false));
  }, []);

  const now = Math.floor(Date.now() / 1000);
  const startOfToday = useMemo(() => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return Math.floor(d.getTime() / 1000);
  }, []);
  const stats = [
    { label: "امروز", value: sumSince(sales, startOfToday) },
    { label: "۷ روز اخیر", value: sumSince(sales, now - 7 * DAY) },
    { label: "۳۰ روز اخیر", value: sumSince(sales, now - 30 * DAY) },
  ];
  const pending = orders.filter((row) => row.status === "pending");
  const shown = sales;

  async function addSale(event: FormEvent) {
    event.preventDefault();
    const nextAmount = parseNonNegativeInt(amount);
    if (nextAmount === null) {
      setError("مبلغ را با عدد بنویس.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const data = await api<{ sales: Sale[] }>("/sales", {
        method: "POST",
        body: JSON.stringify({
          title,
          amount: nextAmount,
          customer,
          channel,
        }),
      });
      setSales(data.sales || []);
      setTitle("");
      setAmount("");
      setCustomer("");
      setFormOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ثبت فروش انجام نشد.");
    } finally {
      setBusy(false);
    }
  }

  const amountPreview = parseNonNegativeInt(amount);

  return (
    <AppShell
      header={
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-sm text-muted">فروش</p>
            <h1 className="text-lg font-bold">فروش و سفارش‌ها</h1>
          </div>
          <div className="flex gap-3 text-sm">
            <Link href="/more/wallet" className="text-warm">
              کیف پول
            </Link>
            <Link href="/more/inventory" className="text-warm">
              انبار
            </Link>
          </div>
        </div>
      }
    >
      <div className="h-full space-y-4 overflow-y-auto p-4">
        {error ? (
          <p className="text-sm text-danger" role="alert">
            {error}
          </p>
        ) : null}

        <section aria-label="خلاصهٔ فروش" className="grid grid-cols-3 gap-2">
          {stats.map((item) => (
            <div key={item.label} className="rounded-2xl bg-canvas p-3 shadow-card">
              <p className="text-xs text-muted">{item.label}</p>
              <p className="mt-1 text-base font-bold text-ink">{loading ? "…" : money(item.value)}</p>
              <p className="text-[11px] text-muted">تومان</p>
            </div>
          ))}
        </section>

        {pending.length ? (
          <Card>
            <div className="flex items-center justify-between gap-2">
              <h2 className="font-bold">منتظر پرداخت</h2>
              <span className="rounded-full bg-paper px-2 py-0.5 text-xs text-warm">{pending.length.toLocaleString("fa-IR")} سفارش</span>
            </div>
            <p className="mt-1 text-xs leading-6 text-muted">لینک پرداخت ساخته شده ولی هنوز پرداخت نشده.</p>
            <ul className="mt-2 divide-y divide-line">
              {pending.slice(0, 5).map((row) => (
                <li key={row.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                  <span className="min-w-0 truncate">{row.title || "سفارش"}</span>
                  <span className="shrink-0 text-muted">{money(row.amount)} تومان</span>
                </li>
              ))}
            </ul>
          </Card>
        ) : null}

        <div className="flex items-center justify-between gap-2">
          <h2 className="font-bold">فروش‌ها</h2>
          <Button type="button" variant={formOpen ? "ghost" : "primary"} onClick={() => setFormOpen((open) => !open)}>
            {formOpen ? "بستن" : "ثبت فروش دستی"}
          </Button>
        </div>

        {formOpen ? (
          <Card>
            <form className="space-y-3" onSubmit={(event) => void addSale(event)}>
              <p className="text-xs leading-6 text-muted">فروشی که بیرون از درگاه سوزان گرفته‌ای (کارت‌به‌کارت، حضوری…). وارد کیف پول نمی‌شود.</p>
              <Field label="چه فروختی؟">
                <Input value={title} placeholder="مثلاً انگشتر نقره" onChange={(event) => setTitle(event.target.value)} />
              </Field>
              <Field label="مبلغ (تومان)">
                <Input dir="ltr" inputMode="numeric" value={amount} onChange={(event) => setAmount(event.target.value)} />
              </Field>
              {amountPreview ? <p className="-mt-2 text-xs text-muted">{money(amountPreview)} تومان</p> : null}
              <Field label="مشتری (اختیاری)">
                <Input value={customer} onChange={(event) => setCustomer(event.target.value)} />
              </Field>
              <Field label="کانال">
                <Select value={channel} onChange={(event) => setChannel(event.target.value)}>
                  {channels.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </Select>
              </Field>
              <Button type="submit" className="w-full" disabled={busy || !title.trim() || amountPreview === null}>
                {busy ? "در حال ثبت…" : "ثبت فروش"}
              </Button>
            </form>
          </Card>
        ) : null}

        {loading ? (
          <ul className="space-y-2">
            {Array.from({ length: 3 }).map((_, index) => (
              <li key={index} className="h-20 animate-pulse rounded-2xl bg-canvas" />
            ))}
          </ul>
        ) : shown.length === 0 ? (
          <EmptyState
            title="هنوز فروشی نیامده"
            detail={
                "فروش‌هایی که از درگاه سایت یا لینک پرداخت دایرکت می‌آیند خودکار اینجا می‌نشینند. فروش بیرونی را با «ثبت فروش دستی» وارد کن."
            }
          />
        ) : (
          <ul className="space-y-2">
            {shown.map((sale) => (
              <li key={sale.id}>
                <Card>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate font-medium">{sale.title}</p>
                      <p className="mt-0.5 text-xs text-muted">
                        {sale.channel}
                        {sale.customer ? ` · ${sale.customer}` : ""}
                        {sale.at ? ` · ${formatWhen(sale.at)}` : ""}
                      </p>
                    </div>
                    <p className="shrink-0 text-sm font-bold">{money(sale.amount)} تومان</p>
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </div>
    </AppShell>
  );
}
