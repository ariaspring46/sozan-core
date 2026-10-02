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
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    setFailed(false);
    const run = async () => {
      const token = getToken();
      try {
        const res = await fetch(`${src}${bust ? `?t=${bust}` : ""}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (!res.ok) {
          if (!cancelled) setFailed(true);
          return;
        }
        const blob = await res.blob();
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      } catch {
        if (!cancelled) setFailed(true);
      }
    };
    void run();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [src, bust]);

  // جای خالی هم‌اندازهٔ عکس تا صفحه با رسیدن عکس نپرد؛ اگر عکس نیامد، تپش بی‌پایان نشان داده نمی‌شود.
  const box = `rounded-lg bg-paper ${className || "h-16 w-28"} ${className?.includes("w-auto") ? "min-w-24" : ""}`;
  if (failed) return <div className={box} role="img" aria-label={alt || "عکس در دسترس نیست"} />;
  if (!url) return <div className={`animate-pulse ${box}`} aria-hidden />;
  return <img src={url} alt={alt} className={className} />;
}
