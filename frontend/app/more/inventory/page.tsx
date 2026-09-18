"use client";

import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { InventoryCatalog } from "@/components/inventory-catalog";

export default function InventoryPage() {
  return (
    <AppShell
      header={
        <div>
          <p className="text-sm text-muted">
            <Link href="/more" className="text-warm">
              بیشتر
            </Link>
          </p>
          <h1 className="text-lg font-bold">انبار کالا</h1>
        </div>
      }
    >
      <InventoryCatalog />
    </AppShell>
  );
}
