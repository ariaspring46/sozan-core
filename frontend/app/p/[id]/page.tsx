"use client";

import { FormEvent, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { SozanMark } from "@/components/sozan-mark";
import { getApiBase } from "@/lib/api";
import { money } from "@/lib/digits";

type PayStatus = {
  id: string;
  title: string;
  amount: number;
  status: string;
  stage?: string;
  tracking?: string;
  carrier?: string;
  hasAddress?: boolean;
};

const STAGE: Record<string, string> = {
  preparing: "فروشنده در حال آماده‌سازی سفارش است.",
  shipped: "سفارش ارسال شد.",
  delivered: "سفارش تحویل شد.",
  cancelled: "سفارش لغو شد. فروشنده برای برگشت پول با شما هماهنگ می‌کند.",
};

const LABEL: Record<string, string> = {
  paid: "پرداخت شد",
  pending: "در انتظار پرداخت",
  failed: "پرداخت نشد",
  ok: "پرداخت شد",
  cancel: "پرداخت لغو شد",
  fail: "پرداخت کامل نشد",
  missing: "سفارش پیدا نشد",
};

export default function PublicPayPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [hint, setHint] = useState("");
  const [row, setRow] = useState<PayStatus | null>(null);
  const [error, setError] = useState("");
  const [address, setAddress] = useState("");
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState("");

  useEffect(() => {
    const pay = new URLSearchParams(window.location.search).get("pay") || "";
    setHint(pay);
    if (!id || id === "missing") {
      setError("سفارش پیدا نشد");
      return;
    }
    void fetch(`${getApiBase()}/p/${encodeURIComponent(id)}/status`)
      .then(async (res) => {
        if (!res.ok) throw new Error("سفارش پیدا نشد");
        return (await res.json()) as PayStatus;
      })
      .then(setRow)
      .catch((err) => setError(err instanceof Error ? err.message : "خطا"));
  }, [id]);

  const status = row?.status || hint;
  const title = row?.title || "پرداخت";
  const ok = status === "paid" || status === "ok";
  const stage = row?.stage || "";
  const canAddress = !!row && ["paid", "awaiting_receipt", "pending"].includes(row.status) && ["", "preparing"].includes(stage);
  const askAddress = canAddress && (!row?.hasAddress || editing);

  async function sendAddress(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setSaved("");
    try {
      const res = await fetch(`${getApiBase()}/p/orders/${encodeURIComponent(id)}/address`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ address }),
      });
      const data = (await res.json().catch(() => ({}))) as PayStatus & { detail?: string };
      if (!res.ok) throw new Error(data.detail || "ثبت آدرس انجام نشد.");
      setRow(data);
      setEditing(false);
      setSaved("آدرس ثبت شد.");
    } catch (err) {
      setSaved(err instanceof Error ? err.message : "ثبت آدرس انجام نشد.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="flex min-h-dvh items-center justify-center bg-canvas p-6">
      <Card className="w-full max-w-md space-y-4">
        <div className="flex items-center gap-3">
          <SozanMark className="h-14 w-14" />
          <div>
            <p className="text-xs text-warm">سوزان</p>
            <h1 className="text-xl font-bold">{LABEL[status] || "رسید پرداخت"}</h1>
          </div>
        </div>
        <p className="font-medium">{title}</p>
        {row?.amount ? <p className="text-sm">{money(row.amount)} تومان</p> : null}
        {error ? <p className="text-sm text-danger">{error}</p> : null}
        {ok && !stage ? <p className="text-sm text-signal">پرداخت ثبت شد. می‌توانی این صفحه را ببندی.</p> : null}
        {stage ? (
          <div className="space-y-1 rounded-xl bg-canvas p-3 text-sm">
            <p className="font-medium">{stage === "cancelled" && row?.status !== "paid" ? "سفارش لغو شد." : STAGE[stage] || stage}</p>
            {stage === "shipped" && row?.tracking ? (
              <p>
                {row.carrier ? `${row.carrier} · ` : ""}کد رهگیری: <span dir="ltr" className="select-all font-bold">{row.tracking}</span>
              </p>
            ) : null}
          </div>
        ) : null}
        {askAddress ? (
          <form className="space-y-2" onSubmit={(event) => void sendAddress(event)}>
            <label className="block text-sm font-medium" htmlFor="ship-address">
              آدرس ارسال
            </label>
            <textarea
              id="ship-address"
              className="min-h-24 w-full rounded-xl border border-line bg-surface p-3 text-sm leading-6"
              placeholder="شهر، خیابان، پلاک، واحد و کد پستی"
              maxLength={400}
              value={address}
              onChange={(event) => setAddress(event.target.value)}
            />
            <Button type="submit" className="w-full" disabled={saving || address.trim().length < 10}>
              {saving ? "در حال ثبت…" : "ثبت آدرس"}
            </Button>
          </form>
        ) : canAddress && row?.hasAddress ? (
          <p className="text-sm text-muted">
            آدرس ثبت شده.{" "}
            <button type="button" className="text-warm underline" onClick={() => setEditing(true)}>
              عوضش کن
            </button>
          </p>
        ) : null}
        {saved ? <p className="text-sm text-muted">{saved}</p> : null}
      </Card>
    </main>
  );
}
