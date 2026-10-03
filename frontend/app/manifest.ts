import type { MetadataRoute } from "next";
import { headers } from "next/headers";
import { isPanelHost } from "@/lib/site-host";
import { THEME_BAR } from "@/lib/theme";

/** پنل نصب‌شدنی مثل اپ (اندروید: «نصب برنامه»، تمام‌صفحه و آیکن خودش)؛ لندینگ فقط آیکن و نام دارد. */
export default async function manifest(): Promise<MetadataRoute.Manifest> {
  const panel = isPanelHost((await headers()).get("host"));
  return {
    name: "سوزان — دستیار فروش",
    short_name: "سوزان",
    description: "فروشگاه، محتوا و پیام مشتری، همه از یک چت.",
    lang: "fa",
    dir: "rtl",
    id: "/chat",
    start_url: panel ? "/chat" : "/",
    scope: "/",
    display: panel ? "standalone" : "browser",
    orientation: "portrait",
    background_color: THEME_BAR.dark,
    theme_color: THEME_BAR.dark,
    categories: ["business", "shopping", "productivity"],
    icons: [
      { src: "/icons/sozan-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/sozan-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/sozan-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
