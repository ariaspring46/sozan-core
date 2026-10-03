import type { Metadata } from "next";
import { headers } from "next/headers";
import { LandingPage } from "@/components/landing-page";
import { PanelHome } from "@/components/panel-home";
import { isPanelHost, panelOriginFromHost } from "@/lib/site-host";

export const dynamic = "force-dynamic";

export async function generateMetadata(): Promise<Metadata> {
  const host = (await headers()).get("host");
  if (isPanelHost(host)) {
    return { title: "سوزان" };
  }
  const origin = "https://sozan-core.ir";
  const title = "سوزان — بگو، بساز، بفروش";
  const description =
    "سوزان دستیار فروش فروشنده‌های ایرانی است: در چت فروشگاه اینترنتی می‌سازی، پست و کپشن می‌گیری و پیام مشتری‌های اینستاگرام و تلگرام را یک‌جا جواب می‌دهی.";
  const image = `${origin}/sozan-mark.png`;
  return {
    metadataBase: new URL(origin),
    title,
    description,
    alternates: { canonical: origin },
    openGraph: {
      title,
      description,
      url: origin,
      siteName: "سوزان",
      locale: "fa_IR",
      type: "website",
      images: [{ url: image, width: 512, height: 512, alt: "سوزان" }],
    },
    twitter: {
      card: "summary",
      title,
      description,
      images: [image],
    },
  };
}

export default async function Home() {
  const host = (await headers()).get("host");
  if (isPanelHost(host)) {
    return <PanelHome />;
  }
  return <LandingPage panelOrigin={panelOriginFromHost(host)} />;
}
