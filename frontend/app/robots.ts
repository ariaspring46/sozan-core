import type { MetadataRoute } from "next";
import { headers } from "next/headers";
import { isPanelHost } from "@/lib/site-host";

/** لندینگ دیده شود؛ پنل فروشنده (app.) در نتایج جستجو نیاید. */
export default async function robots(): Promise<MetadataRoute.Robots> {
  if (isPanelHost((await headers()).get("host"))) {
    return { rules: { userAgent: "*", disallow: "/" } };
  }
  return {
    rules: { userAgent: "*", allow: "/" },
    sitemap: "https://sozan-core.ir/sitemap.xml",
    host: "https://sozan-core.ir",
  };
}
