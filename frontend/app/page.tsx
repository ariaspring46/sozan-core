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
  return {
    title: "سوزان — بگو، بساز، بفروش",
    description: "سوزان فروشگاهت را از دل کانال‌هایت می‌سازد، محتوا را می‌نویسد و جواب پیام‌هایت را در همه‌ی شبکه‌های اجتماعی می‌دهد.",
  };
}

export default async function Home() {
  const host = (await headers()).get("host");
  if (isPanelHost(host)) {
    return <PanelHome />;
  }
  return <LandingPage panelOrigin={panelOriginFromHost(host)} />;
}
