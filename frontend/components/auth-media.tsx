"use client";

import { useEffect, useState } from "react";
import { fileUrl, getToken } from "@/lib/api";

export function AuthMedia({
  campaignId,
  relPath,
  kind,
  alt,
}: {
  campaignId: string;
  relPath: string;
  kind: string;
  alt: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    const run = async () => {
      setFailed(false);
      const token = getToken();
      try {
        const res = await fetch(fileUrl(campaignId, relPath), {
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
  }, [campaignId, relPath, tick]);

  if (failed) {
    return (
      <button type="button" className="text-xs text-danger" onClick={() => setTick((n) => n + 1)}>
        بارگذاری نشد · تلاش دوباره
      </button>
    );
  }
  if (!url) return <div className="aspect-square w-full animate-pulse rounded-lg bg-paper" />;
  if (kind === "video" || relPath.endsWith(".mp4")) {
    return <video className="w-full rounded-lg" src={url} controls playsInline />;
  }
  return <img className="w-full rounded-lg" src={url} alt={alt} />;
}
