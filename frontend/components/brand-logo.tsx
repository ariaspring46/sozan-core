"use client";

import { useEffect, useState } from "react";
import { brandLogoUrl, getToken } from "@/lib/api";

export function BrandLogo({ bust, className }: { bust?: number; className?: string }) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    let objectUrl: string | null = null;
    const run = async () => {
      const token = getToken();
      const res = await fetch(brandLogoUrl(bust), {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) return;
      const blob = await res.blob();
      objectUrl = URL.createObjectURL(blob);
      setUrl(objectUrl);
    };
    void run();
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [bust]);

  if (!url) {
    return <div className={`h-16 w-28 animate-pulse rounded-lg bg-paper ${className || ""}`} />;
  }
  return <img src={url} alt="لوگوی سوزان" className={`h-16 w-auto object-contain ${className || ""}`} />;
}
