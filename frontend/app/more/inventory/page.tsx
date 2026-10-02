"use client";

import { Suspense } from "react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { InventoryCatalog } from "@/components/inventory-catalog";

export default function InventoryPage() {
  return (
    <AppShell
      header={
        <div>
          <p className="text-sm text-muted">
            <Link href="/more" className="tap text-warm">
              بیشتر
            </Link>
          </p>
          <h1 className="text-lg font-bold">انبار کالا</h1>
        </div>
      }
    >
      <Suspense fallback={<p className="px-4 text-sm text-muted">در حال بارگذاری انبار…</p>}>
        <InventoryCatalog />
      </Suspense>
    </AppShell>
  );
}
