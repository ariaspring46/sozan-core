"use client";

import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { BrandIdentitySection } from "@/components/brand-identity";

export default function BrandPage() {
  return (
    <AppShell
      header={
        <div>
          <p className="text-sm text-muted">
            <Link href="/more" className="tap text-warm">
              بیشتر
            </Link>
          </p>
          <h1 className="text-lg font-bold">هویت و لوگو</h1>
        </div>
      }
    >
      <main className="h-full space-y-6 overflow-y-auto p-4 [&>*]:mx-auto [&>*]:max-w-3xl">
        <p className="text-sm text-muted">
          لوگو روی پوستر و ریلز می‌نشیند. توضیح کامل هم برای نوشتن کپشن‌ها نگه داشته می‌شود.
        </p>
        <BrandIdentitySection />
      </main>
    </AppShell>
  );
}
