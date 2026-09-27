import type { Metadata } from "next";
import { LegalPage } from "@/components/legal-page";

export const metadata: Metadata = { title: "لغو اشتراک و بازگشت وجه — سوزان" };

export default function RefundPage() {
  return (
    <LegalPage title="لغو اشتراک و بازگشت وجه">
      <p>تا ۷ روز بعد از خرید، اگر از اشتراک استفاده نشده باشد، کل مبلغ برمی‌گردد.</p>
      <p>درخواست را با تلفن ۰۳۴۹۱۰۹۹۵۸۰ یا از پشتیبانی داخل پنل ثبت کن.</p>
    </LegalPage>
  );
}
