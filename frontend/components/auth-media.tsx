"use client";

import { useEffect, useRef, useState } from "react";
import { Play } from "lucide-react";
import { fileUrl, getToken } from "@/lib/api";

/** نسبت واقعی خروجی‌های استودیو؛ جای تصویر از اول رزرو می‌شود تا صفحه با رسیدن عکس‌ها نپرد. */
export const MEDIA_RATIO: Record<string, string> = {
  feed: "1 / 1",
  channel_post: "1 / 1",
  still: "1 / 1",
  story: "9 / 16",
  reel: "9 / 16",
  wide: "16 / 9",
};

export async function fetchMediaBlob(campaignId: string, relPath: string): Promise<Blob> {
  const token = getToken();
  const res = await fetch(fileUrl(campaignId, relPath), { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new Error("media");
  return res.blob();
}

/** دانلود یک خروجی (با توکن، پس لینک ساده نمی‌شود). */
export async function downloadMedia(campaignId: string, relPath: string, filename: string) {
  const blob = await fetchMediaBlob(campaignId, relPath);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 4000);
}

/**
 * عکس یا ویدیوی یک کمپین. عکس فقط وقتی به صفحه نزدیک شد گرفته می‌شود (کتابخانه ده‌ها فایل چند مگابایتی دارد)؛
 * ویدیو تا لمس «پخش» اصلاً گرفته نمی‌شود.
 */
export function AuthMedia({
  campaignId,
  relPath,
  kind,
  alt,
  ratio = "1 / 1",
  eager = false,
}: {
  campaignId: string;
  relPath: string;
  kind: string;
  alt: string;
  ratio?: string;
  eager?: boolean;
}) {
  const isVideo = kind === "video" || relPath.endsWith(".mp4");
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [tick, setTick] = useState(0);
  const [near, setNear] = useState(eager);
  const [wanted, setWanted] = useState(false);
  const [loading, setLoading] = useState(false);
  const holder = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (near) return;
    const el = holder.current;
    if (!el || typeof IntersectionObserver === "undefined") {
      setNear(true);
      return;
    }
    const watcher = new IntersectionObserver(
      (rows) => {
        if (rows.some((row) => row.isIntersecting)) {
          setNear(true);
          watcher.disconnect();
        }
      },
      { rootMargin: "500px 0px" },
    );
    watcher.observe(el);
    return () => watcher.disconnect();
  }, [near]);

  const load = isVideo ? wanted : near;

  useEffect(() => {
    if (!load) return;
    let objectUrl: string | null = null;
    let cancelled = false;
    setFailed(false);
    setLoading(true);
    fetchMediaBlob(campaignId, relPath)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [campaignId, relPath, tick, load]);

  if (failed) {
    return (
      <button type="button" className="inline-flex min-h-11 items-center text-sm text-danger" onClick={() => setTick((n) => n + 1)}>
        بارگذاری نشد · تلاش دوباره
      </button>
    );
  }
  if (url && isVideo) {
    return <video className="w-full rounded-lg bg-black" style={{ aspectRatio: ratio }} src={url} controls playsInline autoPlay />;
  }
  if (url) {
    return <img className="h-auto w-full rounded-lg" style={{ aspectRatio: ratio }} src={url} alt={alt} />;
  }
  return (
    <div
      ref={holder}
      className="relative flex w-full items-center justify-center overflow-hidden rounded-lg bg-canvas"
      style={{ aspectRatio: ratio }}
    >
      {isVideo ? (
        <button
          type="button"
          onClick={() => setWanted(true)}
          disabled={loading}
          className="inline-flex min-h-11 items-center gap-2 rounded-full bg-accentStrong px-5 text-sm font-medium text-onAccent disabled:opacity-60"
        >
          <Play size={16} aria-hidden="true" />
          {loading ? "در حال گرفتن ویدیو…" : "پخش ویدیو"}
        </button>
      ) : (
        <span className="sr-only">در حال بارگذاری تصویر</span>
      )}
      {!isVideo ? <div className="absolute inset-0 animate-pulse bg-line/30" aria-hidden="true" /> : null}
    </div>
  );
}
