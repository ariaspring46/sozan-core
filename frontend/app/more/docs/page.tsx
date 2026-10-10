import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { SELLER_GUIDES } from "@/lib/seller-guides";

export default function MoreDocsPage() {
  return (
    <AppShell
      header={
        <div>
          <p className="text-sm text-muted">
            <Link href="/more" className="tap text-warm">
              بیشتر
            </Link>
          </p>
          <h1 className="text-lg font-bold">اسناد آموزشی</h1>
        </div>
      }
    >
      <div className="h-full space-y-4 overflow-y-auto p-4 [&>*]:mx-auto [&>*]:max-w-3xl">
        <p className="text-sm leading-7 text-muted">از ورود تا دامنه و ویرایش فروشگاه؛ هر کارت یک راهنمای کوتاه است.</p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {SELLER_GUIDES.map((item) => (
            <Link key={item.slug} href={`/more/docs/${item.slug}`} className="block rounded-2xl border border-line/80 bg-surface p-4 shadow-card">
              <p className="font-bold">{item.title}</p>
              <p className="mt-1 text-[13px] leading-6 text-muted">{item.hint}</p>
            </Link>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
