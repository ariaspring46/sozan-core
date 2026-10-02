import type { ReactNode } from "react";
import { SozanMark } from "@/components/sozan-mark";

const LINKS = [
  { href: "/about", label: "درباره ما" },
  { href: "/contact", label: "تماس با ما" },
  { href: "/terms", label: "قوانین و مقررات" },
  { href: "/refund", label: "لغو اشتراک و بازگشت وجه" },
] as const;

export function LegalPage({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="sozan-landing min-h-dvh bg-canvas text-ink">
      <link rel="preload" href="/fonts/estedad-arabic.woff2" as="font" type="font/woff2" crossOrigin="anonymous" />
      <link rel="preload" href="/fonts/estedad-latin.woff2" as="font" type="font/woff2" crossOrigin="anonymous" />
      <header className="border-b border-line/40">
        <div className="mx-auto flex h-16 max-w-3xl items-center justify-between px-5">
          <a href="/" className="flex min-h-11 items-center gap-3">
            <SozanMark className="h-8 w-8" glow={false} />
            <span className="text-sm font-medium text-warm">سوزان</span>
          </a>
          <a href="/login" className="inline-flex min-h-11 items-center rounded-xl px-3 text-sm text-ink/80 hover:text-ink">
            ورود
          </a>
        </div>
        <nav aria-label="صفحه‌های حقوقی" className="mx-auto hidden max-w-3xl flex-wrap gap-x-5 gap-y-1 px-5 pb-3 text-sm text-ink/75 sm:flex">
          {LINKS.map((item) => (
            <a key={item.href} href={item.href} className="inline-flex min-h-11 items-center hover:text-ink">
              {item.label}
            </a>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-3xl px-5 py-12">
        <h1 className="landing-display text-3xl">{title}</h1>
        <div className="mt-8 space-y-4 text-[15px] leading-8 text-ink/85">{children}</div>
      </main>
      <footer className="border-t border-line/40">
        <nav aria-label="پیوندهای پایین صفحه" className="mx-auto flex max-w-3xl flex-wrap gap-x-5 gap-y-1 px-5 pt-6 text-sm text-ink/75">
          {LINKS.map((item) => (
            <a key={item.href} href={item.href} className="inline-flex min-h-11 items-center hover:text-warm">
              {item.label}
            </a>
          ))}
        </nav>
        <p className="mx-auto max-w-3xl px-5 py-4 text-center text-xs leading-6 text-ink/65">
          ساخته شده توسط شرکت گهر شبکه کارمانیا
        </p>
      </footer>
    </div>
  );
}
