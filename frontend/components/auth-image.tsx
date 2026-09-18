"use client";

import { useEffect, useState } from "react";
import { getToken } from "@/lib/api";

export function AuthImage({
  src,
  alt,
  className,
  bust,
}: {
  src: string;
  alt: string;
  className?: string;
  bust?: number;
}) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    let objectUrl: string | null = null;
    const run = async () => {
      const token = getToken();
      const res = await fetch(`${src}${bust ? `?t=${bust}` : ""}`, {
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
  }, [src, bust]);

  if (!url) return <div className={`animate-pulse rounded-lg bg-paper ${className || "h-16 w-28"}`} />;
  return <img src={url} alt={alt} className={className} />;
}
