"use client";

import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { clearToken } from "@/lib/api";

const HUB = [
  { href: "/more/docs", title: "اسناد آموزشی", hint: "از ورود تا دامنه و ویرایش" },
  { href: "/more/channels", title: "کانال‌ها", hint: "اینستاگرام تا روبیکا" },
  { href: "/more/inventory", title: "انبار", hint: "کالا، قیمت و موجودی" },
  { href: "/brand", title: "هویت و لوگو", hint: "نام سوزان و موشن" },
  { href: "/campaigns", title: "کمپین‌ها", hint: "پست‌های ساخته‌شده" },
  { href: "/more/settings", title: "پرداخت و پیامک", hint: "درگاه، OTP و اشتراک" },
  { href: "/more/wallet", title: "کیف پول", hint: "مانده، برداشت شبا و پیامک" },
] as const;

export default function MorePage() {
  return (
    <AppShell
      header={
        <div>
          <p className="text-sm text-muted">بیشتر</p>
          <h1 className="text-lg font-bold">همهٔ ابزارها</h1>
        </div>
      }
    >
      <div className="h-full space-y-4 overflow-y-auto p-4">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
          {HUB.map((item) => (
            <Link key={item.href} href={item.href} className="rounded-2xl bg-canvas p-4 shadow-card">
              <p className="font-bold">{item.title}</p>
              <p className="mt-1 text-xs leading-6 text-muted">{item.hint}</p>
            </Link>
          ))}
        </div>
        <Button
          variant="ghost"
          className="w-full"
          onClick={() => {
            clearToken();
            window.location.href = "/login";
          }}
        >
          خروج
        </Button>
      </div>
    </AppShell>
  );
}
