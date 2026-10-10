"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

type Policy = Record<string, string | number>;

const TEXT_FIELDS: { key: string; label: string }[] = [
  { key: "shippingMethod", label: "روش ارسال" },
  { key: "shippingDays", label: "زمان ارسال" },
  { key: "shippingCities", label: "شهرهای ارسال" },
  { key: "returnNote", label: "شرط مرجوعی" },
  { key: "returnPayer", label: "هزینهٔ برگشت با" },
  { key: "hours", label: "ساعت پاسخ" },
  { key: "sizeExchange", label: "تعویض سایز" },
  { key: "invoice", label: "فاکتور" },
  { key: "cod", label: "پرداخت در محل" },
  { key: "cardToCard", label: "کارت به کارت" },
  { key: "cardNumber", label: "شماره کارت (۱۶ رقم، برای رسید)" },
  { key: "sheba", label: "شبا (IR…، برای رسید)" },
  { key: "accountHolder", label: "نام صاحب حساب (برای رسید)" },
];

const NUMBER_FIELDS: { key: string; label: string }[] = [
  { key: "shippingCost", label: "هزینهٔ ارسال (تومان)" },
  { key: "freeShippingFrom", label: "ارسال رایگان از (تومان)" },
  { key: "returnDays", label: "مهلت مرجوعی (روز)" },
  { key: "minOrder", label: "حداقل خرید (تومان)" },
];

export function SalesPolicyForm() {
  const [form, setForm] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    void api<Policy>("/settings/sales-policy")
      .then((data) => {
        const next: Record<string, string> = {};
        for (const field of [...TEXT_FIELDS, ...NUMBER_FIELDS]) {
          const value = data[field.key];
          next[field.key] = value == null ? "" : String(value);
        }
        setForm(next);
      })
      .catch(() => setForm({}));
  }, []);

  function set(key: string, value: string) {
    setSaved(false);
    setForm((current) => ({ ...current, [key]: value }));
  }

  return (
    <section id="shipping" aria-label="ارسال و مرجوعی" className="scroll-mt-16 rounded-2xl border border-line/80 bg-surface p-4 shadow-card">
      <h2 className="text-base font-bold">ارسال و مرجوعی</h2>
      <p className="mt-1 text-sm text-muted">فیلد خالی یعنی هنوز ثبت نشده و دایرکت همان موضوع را به خودت می‌سپارد.</p>
      <div className="mt-3 space-y-3">
        {NUMBER_FIELDS.map((field) => (
          <label key={field.key} className="block text-sm">
            <span className="mb-1 block text-muted">{field.label}</span>
            <Input value={form[field.key] || ""} inputMode="numeric" onChange={(event) => set(field.key, event.target.value)} />
          </label>
        ))}
        {TEXT_FIELDS.map((field) => (
          <label key={field.key} className="block text-sm">
            <span className="mb-1 block text-muted">{field.label}</span>
            <Input value={form[field.key] || ""} onChange={(event) => set(field.key, event.target.value)} />
          </label>
        ))}
      </div>
      {error ? <p className="mt-2 text-sm text-danger">{error}</p> : null}
      {saved ? <p className="mt-2 text-sm text-muted">ذخیره شد.</p> : null}
      <Button
        className="mt-3"
        type="button"
        disabled={busy}
        onClick={() => {
          setBusy(true);
          setError("");
          const body: Record<string, string | null> = {};
          for (const field of [...TEXT_FIELDS, ...NUMBER_FIELDS]) {
            const raw = (form[field.key] || "").trim();
            body[field.key] = raw || null;
          }
          void api<Policy>("/settings/sales-policy", { method: "PUT", body: JSON.stringify(body) })
            .then(() => setSaved(true))
            .catch((err) => setError(err instanceof Error ? err.message : "ذخیره نشد"))
            .finally(() => setBusy(false));
        }}
      >
        ذخیرهٔ ارسال و مرجوعی
      </Button>
    </section>
  );
}
