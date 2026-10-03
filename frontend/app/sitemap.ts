import type { MetadataRoute } from "next";

const ORIGIN = "https://sozan-core.ir";
const PAGES: [string, number][] = [
  ["", 1],
  ["/about", 0.6],
  ["/contact", 0.6],
  ["/terms", 0.4],
  ["/refund", 0.4],
];

export default function sitemap(): MetadataRoute.Sitemap {
  return PAGES.map(([path, priority]) => ({ url: `${ORIGIN}${path}`, changeFrequency: "weekly", priority }));
}
