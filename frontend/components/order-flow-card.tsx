"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { api } from "@/lib/api";
import { formatWhen, money, toLatinDigits } from "@/lib/digits";

export type OrderEvent = { at: number; event: string; note?: string };

export type FlowOrder = {
  id: string;
  title: string;
  amount: number;
  status: string;
  channel: string;
  at?: number;
  stage?: string;
  tracking?: string;
  carrier?: string;
  customer?: string;
  customerMobile?: string;
  address?: string;
  history?: OrderEvent[];
};

const STAGE: Record<string, string> = {
  "": "منتظر ارسال",
  preparing: "در حال آماده‌سازی",
  shipped: "ارسال‌شده",
  delivered: "تحویل‌شده",
  cancelled: "لغوشده",
};

const EVENT: Record<string, string> = {
  created: "ثبت سفارش",
  paid: "پرداخت",
  failed: "پرداخت ناموفق",
  receipt: "رسید آمد",
  receipt_rejected: "رسید رد شد",
  needsAction: "موجودی کم بود",
  address: "آدرس",
  preparing: "آماده‌سازی",
  shipped: "ارسال",
  delivered: "تحویل",
  cancelled: "لغو",
  notified: "خبر به مشتری",
};

const TOLD: Record<string, string> = {
  dm: "در دایرکت",
  sms: "با پیامک",
  none: "راهی نبود؛ خودت خبر بده",
  "dm-failed": "دایرکت نرسید؛ خودت خبر بده",
  "sms-failed": "پیامک نرسید؛ خودت خبر بده",
  "sms-quota": "سقف پیامک تمام است؛ خودت خبر بده",
};

const CARRIERS = ["پست", "تیپاکس", "پیک", "چاپار"];

/** سفارش‌های پرداخت‌شده‌ای که هنوز کار دارند: آماده‌سازی، ارسال با کد رهگیری، تحویل یا لغو. */
export function OrderFlowCard({ orders, onChanged }: { orders: FlowOrder[]; onChanged: (row: FlowOrder) => void }) {
  const open = orders.filter((row) => row.status === "paid" && !["delivered", "cancelled"].includes(row.stage || ""));
  if (!open.length) return null;
  return (
    <Card>
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-bold">سفارش‌های در جریان</h2>
        <span className="shrink-0 rounded-full bg-paper px-2.5 py-0.5 text-xs text-warm">{open.length.toLocaleString("fa-IR")} سفارش</span>
      </div>
      <p className="mt-1 text-sm leading-6 text-muted">پول این‌ها رسیده. وقتی فرستادی «ارسال شد» را بزن تا به مشتری خبر برسد.</p>
      <ul className="mt-2 divide-y divide-line">
        {open.slice(0, 20).map((row) => (
          <OrderRow key={row.id} row={row} onChanged={onChanged} />
        ))}
      </ul>
    </Card>
  );
}

function OrderRow({ row, onChanged }: { row: FlowOrder; onChanged: (row: FlowOrder) => void }) {
  const [mode, setMode] = useState<"" | "ship" | "cancel">("");
  const [tracking, setTracking] = useState("");
  const [carrier, setCarrier] = useState(CARRIERS[0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [told, setTold] = useState("");
  const stage = row.stage || "";

  async function move(next: string) {
    setBusy(true);
    setError("");
    try {
      const out = await api<FlowOrder & { notified?: string }>(`/pay/orders/${encodeURIComponent(row.id)}/stage`, {
        method: "POST",
        body: JSON.stringify({ stage: next, tracking: next === "shipped" ? toLatinDigits(tracking.trim()) : "", carrier: next === "shipped" ? carrier : "" }),
      });
      setMode("");
      setTold(out.notified && out.notified !== "none" ? `خبر به مشتری: ${TOLD[out.notified] || out.notified}` : next === "shipped" || next === "cancelled" ? `خبر به مشتری: ${TOLD.none}` : "");
      onChanged(out);
    } catch (err) {
      setError(err instanceof Error ? err.message : "انجام نشد.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="space-y-2 py-3 text-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-medium">{row.title || "سفارش"}</p>
          <p className="wrap-any text-xs leading-5 text-muted">
            {row.customer || "مشتری"}
            {row.customerMobile ? (
              <>
                {" · "}
                <a dir="ltr" className="text-warm underline" href={`tel:${row.customerMobile}`}>
                  {row.customerMobile}
                </a>
              </>
            ) : null}
            {row.at ? ` · ${formatWhen(row.at)}` : ""}
          </p>
        </div>
        <div className="shrink-0 text-left">
          <p className="whitespace-nowrap font-bold">{money(row.amount)} تومان</p>
          <span className="mt-1 inline-block rounded-full bg-paper px-2 py-0.5 text-xs text-warm">{STAGE[stage] || stage}</span>
        </div>
      </div>
      <p className="wrap-any text-xs leading-5">{row.address ? `آدرس: ${row.address}` : <span className="text-muted">آدرس هنوز ثبت نشده (مشتری در صفحهٔ سفارشش می‌نویسد).</span>}</p>
      {stage === "shipped" && row.tracking ? (
        <p className="text-xs leading-5 text-muted">
          {row.carrier ? `${row.carrier} · ` : ""}کد رهگیری <span dir="ltr">{row.tracking}</span>
        </p>
      ) : null}

      {mode === "ship" ? (
        <div className="space-y-2 rounded-xl bg-canvas p-3">
          <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2">
            <Input dir="ltr" inputMode="numeric" placeholder="کد رهگیری (اختیاری)" value={tracking} onChange={(event) => setTracking(event.target.value)} />
            <Select value={carrier} onChange={(event) => setCarrier(event.target.value)}>
              {CARRIERS.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </Select>
          </div>
          <div className="flex gap-2">
            <Button type="button" disabled={busy} onClick={() => void move("shipped")}>
              {busy ? "…" : "ثبت ارسال و خبر به مشتری"}
            </Button>
            <Button type="button" variant="ghost" disabled={busy} onClick={() => setMode("")}>
              بستن
            </Button>
          </div>
        </div>
      ) : mode === "cancel" ? (
        <div className="space-y-2 rounded-xl bg-canvas p-3">
          <p className="text-xs leading-5 text-danger">لغو شود؟ برگرداندن پول با خودت است؛ سوزان پول را برنمی‌گرداند.</p>
          <div className="flex gap-2">
            <Button type="button" disabled={busy} onClick={() => void move("cancelled")}>
              {busy ? "…" : "لغو سفارش"}
            </Button>
            <Button type="button" variant="ghost" disabled={busy} onClick={() => setMode("")}>
              نه
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {stage === "" ? (
            <Button type="button" variant="ghost" disabled={busy} onClick={() => void move("preparing")}>
              آماده‌سازی
            </Button>
          ) : null}
          {stage !== "shipped" ? (
            <Button type="button" disabled={busy} onClick={() => setMode("ship")}>
              ارسال شد
            </Button>
          ) : (
            <Button type="button" disabled={busy} onClick={() => void move("delivered")}>
              تحویل شد
            </Button>
          )}
          {stage !== "shipped" ? (
            <Button type="button" variant="ghost" disabled={busy} onClick={() => setMode("cancel")}>
              لغو
            </Button>
          ) : null}
        </div>
      )}
      {error ? (
        <p className="text-xs text-danger" role="alert">
          {error}
        </p>
      ) : null}
      {told ? <p className="text-xs text-muted">{told}</p> : null}
      {row.history?.length ? (
        <details className="text-xs text-muted">
          <summary className="cursor-pointer select-none">تاریخچه</summary>
          <ol className="mt-1 space-y-0.5">
            {row.history.map((item, index) => (
              <li key={`${item.at}-${index}`}>
                {formatWhen(item.at)} · {EVENT[item.event] || item.event}
                {item.note ? ` · ${item.event === "notified" ? TOLD[item.note] || item.note : item.note}` : ""}
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </li>
  );
}
