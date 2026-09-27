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
    <div className="sozan-landing min-h-screen bg-canvas text-ink">
      <header className="border-b border-line/40">
        <div className="mx-auto flex h-16 max-w-3xl items-center justify-between px-5">
          <a href="/" className="flex items-center gap-3">
            <SozanMark className="h-8 w-8" glow={false} />
            <span className="text-sm font-medium text-warm">سوزان</span>
          </a>
          <a href="/login" className="text-sm text-ink/70 hover:text-ink">
            ورود
          </a>
        </div>
        <nav className="mx-auto flex max-w-3xl flex-wrap gap-x-4 gap-y-2 px-5 pb-4 text-xs text-ink/70">
          {LINKS.map((item) => (
            <a key={item.href} href={item.href} className="hover:text-ink">
              {item.label}
            </a>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-3xl px-5 py-12">
        <h1 className="landing-display text-3xl">{title}</h1>
        <div className="mt-8 space-y-4 text-sm leading-8 text-ink/80">{children}</div>
      </main>
      <footer className="border-t border-line/40">
        <nav className="mx-auto flex max-w-3xl flex-wrap gap-x-5 gap-y-2 px-5 pt-8 text-xs text-ink/65">
          {LINKS.map((item) => (
            <a key={item.href} href={item.href} className="hover:text-warm">
              {item.label}
            </a>
          ))}
        </nav>
        <p className="mx-auto max-w-3xl px-5 py-4 text-center text-[11px] leading-6 text-ink/55">
          ساخته شده توسط شرکت گهر شبکه کارمانیا
        </p>
      </footer>
    </div>
  );
}
