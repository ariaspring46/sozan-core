"use client";

import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { clearToken } from "@/lib/api";
import { usePlan } from "@/lib/use-plan";

const HUB = [
  { href: "/more/inventory", title: "انبار", hint: "کالا، قیمت و موجودی" },
  { href: "/more/docs", title: "اسناد آموزشی", hint: "از ورود تا دامنه و ویرایش" },
  { href: "/more/channels", title: "کانال‌ها", hint: "اینستاگرام تا روبیکا" },
  { href: "/brand", title: "هویت و لوگو", hint: "نام، لوگو و حرکت برند" },
  { href: "/studio", title: "استودیو", hint: "پست‌ها و کمپین‌های ساخته‌شده" },
  { href: "/more/settings", title: "پرداخت و پیامک", hint: "اشتراک، درگاه پرداخت و کد ورود" },
  { href: "/more/wallet", title: "کیف پول", hint: "مانده، برداشت شبا و پیامک" },
] as const;

export default function MorePage() {
  const plan = usePlan();
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
        {plan ? (
          <div className="flex items-center justify-between gap-3 rounded-2xl border border-accent/30 bg-canvas p-4 shadow-card">
            <div>
              <p className="text-xs text-muted">پلن فعلی</p>
              <p className="text-lg font-bold">{plan.label}</p>
            </div>
            <Link
              href="/more/settings"
              className={plan.canUpgrade ? "min-h-11 rounded-xl bg-accentStrong px-4 py-2.5 text-sm font-bold text-onAccent" : "min-h-11 rounded-xl border border-line px-4 py-2.5 text-sm text-warm"}
            >
              {plan.canUpgrade ? "ارتقای پلن" : "جزئیات اشتراک"}
            </Link>
          </div>
        ) : null}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
          {HUB.map((item) => (
            <Link key={item.href} href={item.href} className="rounded-2xl bg-canvas p-4 shadow-card">
              <p className="font-bold">{item.title}</p>
              <p className="mt-1 text-xs leading-6 text-muted">{item.hint}</p>
            </Link>
          ))}
        </div>
        <section aria-labelledby="theme-title" className="rounded-2xl bg-canvas p-4 shadow-card">
          <p id="theme-title" className="font-bold">ظاهر پنل</p>
          <p className="mt-1 text-xs leading-6 text-muted">«خودکار» همان روشن یا تیرهٔ گوشی/سیستم را دنبال می‌کند.</p>
          <ThemeToggle className="mt-3" />
        </section>
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
