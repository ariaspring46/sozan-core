import type { Metadata } from "next";
import { LegalPage } from "@/components/legal-page";

export const metadata: Metadata = { title: "درباره ما — سوزان" };

export default function AboutPage() {
  return (
    <LegalPage title="درباره ما">
      <p>سوزان محصول شرکت گهر شبکه کارمانیا است.</p>
      <p>فروشنده با سوزان فروشگاه، محتوا و گفتگو با مشتری را از یک پنل جلو می‌برد.</p>
    </LegalPage>
  );
}
