import type { Metadata, Viewport } from "next";
import { DropStaleWorkers } from "@/components/drop-stale-workers";
import { OnboardGate } from "@/components/onboard-gate";
import { THEME_BAR, THEME_BOOT } from "@/lib/theme";
import "./globals.css";

export const metadata: Metadata = {
  title: "سوزان",
  description: "فروشگاه در چت، استودیوی محتوا، تنظیمات سوزان",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: THEME_BAR.light },
    { media: "(prefers-color-scheme: dark)", color: THEME_BAR.dark },
  ],
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  interactiveWidget: "overlays-content",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fa" dir="rtl" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
        <link rel="preload" href="/fonts/vazirmatn-var.woff2" as="font" type="font/woff2" crossOrigin="anonymous" />
      </head>
      <body className="min-h-dvh bg-canvas font-vazir text-ink antialiased">
        <DropStaleWorkers />
        <OnboardGate>{children}</OnboardGate>
      </body>
    </html>
  );
}
