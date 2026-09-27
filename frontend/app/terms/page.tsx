import type { Metadata } from "next";
import { LegalPage } from "@/components/legal-page";

export const metadata: Metadata = { title: "قوانین و مقررات — سوزان" };

export default function TermsPage() {
  return (
    <LegalPage title="قوانین و مقررات">
      <p>اشتراک سوزان ماهانه است. مبلغی که روی سایت دیده می‌شود همان مبلغی است که در پرداخت گرفته می‌شود.</p>
      <p>
        پیام‌های صندوق برای پیش‌نویس و پاسخ خودکار با سرویس‌های هوش مصنوعی پردازش می‌شود و دادهٔ هر فروشگاه جدا نگه داشته می‌شود.
      </p>
      <p>برای تماس: شرکت گهر شبکه کارمانیا، تلفن ۰۳۴۹۱۰۹۹۵۸۰.</p>
    </LegalPage>
  );
}
