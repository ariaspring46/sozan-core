"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Card } from "@/components/ui/card";
import { SozanMark } from "@/components/sozan-mark";
import { getApiBase } from "@/lib/api";
import { money } from "@/lib/digits";

type PayStatus = {
  id: string;
  title: string;
  amount: number;
  status: string;
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

  return (
    <main className="flex min-h-screen items-center justify-center bg-canvas p-6">
      <Card className="w-full max-w-md space-y-4">
        <div className="flex items-center gap-3">
          <SozanMark className="h-14 w-14" />
          <div>
            <p className="text-[11px] tracking-[0.28em] text-warm">سوزان</p>
            <h1 className="text-xl font-bold">{LABEL[status] || "رسید پرداخت"}</h1>
          </div>
        </div>
        <p className="font-medium">{title}</p>
        {row?.amount ? <p className="text-sm">{money(row.amount)} تومان</p> : null}
        {error ? <p className="text-sm text-danger">{error}</p> : null}
        {ok ? <p className="text-sm text-signal">پرداخت ثبت شد. می‌توانی این صفحه را ببندی.</p> : null}
      </Card>
    </main>
  );
}
