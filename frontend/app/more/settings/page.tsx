"use client";

import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { SalesPolicyForm } from "@/components/sales-policy-form";
import { ShopSettingsForm } from "@/components/shop-settings-form";
import { TrainingChoice } from "@/components/training-choice";

const SECTIONS = [
  ["payment", "پرداخت"],
  ["sms", "پیامک"],
  ["shipping", "ارسال و مرجوعی"],
] as const;

export default function MoreSettingsPage() {
  return (
    <AppShell
      header={
        <div>
          <p className="text-sm text-muted">
            <Link href="/more" className="tap text-warm">
              بیشتر
            </Link>
          </p>
          <h1 className="text-lg font-bold">پرداخت، ارسال و پیامک</h1>
        </div>
      }
    >
      <div className="h-full space-y-4 overflow-y-auto p-4 [&>*]:mx-auto [&>*]:max-w-3xl">
        <nav aria-label="بخش‌های این صفحه" className="sticky top-0 z-10 -mt-4 flex gap-2 overflow-x-auto bg-paper/95 py-3 backdrop-blur-md">
          {SECTIONS.map(([id, label]) => (
            <a
              key={id}
              href={`#${id}`}
              className="tap inline-flex min-h-11 shrink-0 items-center rounded-full border border-line bg-surface px-4 text-sm"
            >
              {label}
            </a>
          ))}
        </nav>
        <ShopSettingsForm />
        <SalesPolicyForm />
        <TrainingChoice />
      </div>
    </AppShell>
  );
}
