"use client";

import Link from "next/link";
import { BookOpen, ChevronLeft, Clapperboard, CreditCard, LifeBuoy, Package, Palette, Share2, Wallet } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { clearToken } from "@/lib/api";
import { usePlan } from "@/lib/use-plan";
import { PushToggle } from "@/components/push-toggle";

/** همهٔ ابزارها در سه گروه؛ هر ردیف آیکون، نام و یک خط توضیح دارد. */
const GROUPS = [
  {
    title: "فروشگاه",
    items: [
      { href: "/more/inventory", title: "انبار", hint: "کالا، قیمت و موجودی", icon: Package },
      { href: "/brand", title: "هویت و لوگو", hint: "نام، لوگو و حرکت برند", icon: Palette },
      { href: "/more/channels", title: "کانال‌ها", hint: "اینستاگرام، تلگرام و بقیه", icon: Share2 },
      { href: "/studio", title: "استودیو", hint: "پست‌ها و کمپین‌های ساخته‌شده", icon: Clapperboard },
    ],
  },
  {
    title: "فروش و پول",
    items: [
      { href: "/more/settings", title: "پرداخت، ارسال و پیامک", hint: "اشتراک، درگاه، ارسال و کد ورود", icon: CreditCard },
      { href: "/more/wallet", title: "کیف پول", hint: "مانده و برداشت شبا", icon: Wallet },
      { href: "/more/support", title: "پشتیبانی و رسیدها", hint: "تیکت مشتری و تأیید کارت‌به‌کارت", icon: LifeBuoy },
    ],
  },
  {
    title: "راهنما",
    items: [{ href: "/more/docs", title: "اسناد آموزشی", hint: "از ورود تا دامنه و ویرایش", icon: BookOpen }],
  },
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
      <div className="h-full space-y-4 overflow-y-auto p-4 [&>*]:mx-auto [&>*]:max-w-3xl">
        {plan ? (
          <div className="flex items-center justify-between gap-3 rounded-2xl border border-line bg-surface p-4">
            <div>
              <p className="text-[13px] text-muted">پلن فعلی</p>
              <p className="text-lg font-bold">{plan.label}</p>
            </div>
            <Link
              href="/more/settings#plans"
              className={plan.canUpgrade ? "min-h-11 rounded-xl bg-accentStrong px-4 py-2.5 text-sm font-bold text-onAccent" : "min-h-11 rounded-xl border border-line px-4 py-2.5 text-sm text-warm"}
            >
              {plan.canUpgrade ? "ارتقای پلن" : "جزئیات اشتراک"}
            </Link>
          </div>
        ) : null}
        {GROUPS.map((group) => (
          <section key={group.title} aria-label={group.title}>
            <h2 className="mb-2 px-1 text-[13px] font-bold text-muted">{group.title}</h2>
            <ul className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface">
              {group.items.map((item) => {
                const Icon = item.icon;
                return (
                  <li key={item.href}>
                    <Link href={item.href} className="flex min-h-16 items-center gap-3 px-4 py-3 hover:bg-canvas">
                      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent/10 text-warm">
                        <Icon size={20} aria-hidden />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block font-bold">{item.title}</span>
                        <span className="block truncate text-[13px] text-muted">{item.hint}</span>
                      </span>
                      <ChevronLeft size={18} className="shrink-0 text-muted" aria-hidden />
                    </Link>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
        <PushToggle />
        <section aria-labelledby="theme-title" className="rounded-2xl border border-line bg-surface p-4">
          <p id="theme-title" className="font-bold">ظاهر پنل</p>
          <p className="mt-1 text-[13px] leading-6 text-muted">«خودکار» همان روشن یا تیرهٔ گوشی/سیستم را دنبال می‌کند.</p>
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
