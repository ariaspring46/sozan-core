import type { Metadata } from "next";
import { LegalPage } from "@/components/legal-page";

export const metadata: Metadata = { title: "تماس با ما — سوزان" };

export default function ContactPage() {
  return (
    <LegalPage title="تماس با ما">
      <p>شرکت گهر شبکه کارمانیا</p>
      <p>نشانی: سیرجان، بلوار چمران، پشت مدرسهٔ فردوس</p>
      <p>تلفن: ۰۳۴۹۱۰۹۹۵۸۰</p>
    </LegalPage>
  );
}
