"use client";

import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { SalesPolicyForm } from "@/components/sales-policy-form";
import { ShopSettingsForm } from "@/components/shop-settings-form";
import { TrainingChoice } from "@/components/training-choice";

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
          <h1 className="text-lg font-bold">پرداخت و پیامک</h1>
        </div>
      }
    >
      <div className="h-full space-y-4 overflow-y-auto p-4 [&>*]:mx-auto [&>*]:max-w-3xl">
        <SalesPolicyForm />
        <TrainingChoice />
        <ShopSettingsForm />
      </div>
    </AppShell>
  );
}
