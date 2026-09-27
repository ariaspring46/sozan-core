"use client";

import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { SalesPolicyForm } from "@/components/sales-policy-form";
import { ShopSettingsForm } from "@/components/shop-settings-form";

export default function MoreSettingsPage() {
  return (
    <AppShell
      header={
        <div>
          <p className="text-sm text-muted">
            <Link href="/more" className="text-warm">
              بیشتر
            </Link>
          </p>
          <h1 className="text-lg font-bold">پرداخت و پیامک</h1>
        </div>
      }
    >
      <div className="space-y-4">
        <SalesPolicyForm />
        <ShopSettingsForm />
      </div>
    </AppShell>
  );
}
