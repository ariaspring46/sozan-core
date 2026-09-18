import type { Metadata, Viewport } from "next";
import { DropStaleWorkers } from "@/components/drop-stale-workers";
import { OnboardGate } from "@/components/onboard-gate";
import "./globals.css";

export const metadata: Metadata = {
  title: "سوزان",
  description: "فروشگاه در چت، استودیوی محتوا، تنظیمات سوزان",
  icons: { icon: "/sozan-mark.png", apple: "/sozan-mark.png" },
};

export const viewport: Viewport = {
  themeColor: "#2F2F33",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  interactiveWidget: "overlays-content",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fa" dir="rtl">
      <head>
        <link rel="preload" href="/fonts/estedad-arabic.woff2" as="font" type="font/woff2" crossOrigin="anonymous" />
        <link rel="preload" href="/fonts/estedad-latin.woff2" as="font" type="font/woff2" crossOrigin="anonymous" />
      </head>
      <body className="min-h-screen bg-canvas font-vazir text-ink antialiased">
        <DropStaleWorkers />
        <OnboardGate>{children}</OnboardGate>
      </body>
    </html>
  );
}
