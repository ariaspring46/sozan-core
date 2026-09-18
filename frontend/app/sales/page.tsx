"use client";

import { FormEvent, useEffect, useState } from "react";
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

type Account = { id: string; label: string; handle: string };

const SHOP_CHANNEL = "فروشگاه";

export default function SalesPage() {
  const [sales, setSales] = useState<Sale[]>([]);
  const [channels, setChannels] = useState<string[]>([SHOP_CHANNEL]);
  const [title, setTitle] = useState("");
  const [amount, setAmount] = useState("");
  const [customer, setCustomer] = useState("");
  const [channel, setChannel] = useState(SHOP_CHANNEL);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    const [saleData, channelData] = await Promise.all([
      api<{ sales: Sale[] }>("/sales"),
      api<{ accounts: Account[] }>("/channels").catch(() => ({ accounts: [] as Account[] })),
    ]);
    setSales(saleData.sales || []);
    const connected = (channelData.accounts || []).map((item) => item.label).filter(Boolean);
    setChannels([SHOP_CHANNEL, ...connected.filter((item, index, all) => item !== SHOP_CHANNEL && all.indexOf(item) === index)]);
  }

  useEffect(() => {
    void load()
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

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
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell
      header={
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-sm text-muted">فروش</p>
            <h1 className="text-lg font-bold">ثبت فروش</h1>
          </div>
          <div className="flex gap-3 text-sm">
            <Link href="/more/wallet" className="text-warm">
              کیف پول
            </Link>
            <Link href="/more/inventory" className="text-warm">
              انبار کالا
            </Link>
          </div>
        </div>
      }
    >
      <div className="h-full space-y-4 overflow-y-auto p-4">
        {error ? <p className="text-sm text-danger">{error}</p> : null}
        <Card>
          <form className="space-y-3" onSubmit={(event) => void addSale(event)}>
            <Field label="شرح فروش">
              <Input value={title} onChange={(event) => setTitle(event.target.value)} />
            </Field>
            <Field label="مبلغ به تومان">
              <Input dir="ltr" inputMode="numeric" value={amount} onChange={(event) => setAmount(event.target.value)} />
            </Field>
            <Field label="مشتری">
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
            <Button type="submit" disabled={busy || !title.trim()}>
              ثبت فروش
            </Button>
          </form>
        </Card>
        {loading ? (
          <ul className="space-y-2">
            {Array.from({ length: 3 }).map((_, index) => (
              <li key={index} className="h-24 animate-pulse rounded-2xl bg-canvas" />
            ))}
          </ul>
        ) : sales.length === 0 ? (
          <EmptyState title="هنوز فروشی ثبت نشده" detail="اولین فروش را از فرم بالا وارد کن." />
        ) : (
          <ul className="space-y-2">
            {sales.map((sale) => (
              <li key={sale.id}>
                <Card>
                  <p className="text-xs text-warm">{sale.channel}</p>
                  <p className="font-medium">{sale.title}</p>
                  <p className="text-sm">{money(sale.amount)} تومان</p>
                  <p className="text-sm text-muted">{sale.customer}</p>
                  {sale.at ? <p className="text-xs text-muted">{formatWhen(sale.at)}</p> : null}
                </Card>
              </li>
            ))}
          </ul>
        )}
      </div>
    </AppShell>
  );
}
