"use client";

import { useEffect, useRef, useState } from "react";
import { chatMediaUrl, getToken } from "@/lib/api";

export function ChatAttach({ kind, name }: { kind: string; name: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [tick, setTick] = useState(0);
  const [near, setNear] = useState(false);
  const holder = useRef<HTMLDivElement>(null);

  // یک گفتگوی پرکار ده‌ها رسانهٔ چندمگابایتی دارد؛ هر کدام فقط وقتی نزدیک صفحه شد گرفته می‌شود.
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
      { rootMargin: "400px 0px" },
    );
    watcher.observe(el);
    return () => watcher.disconnect();
  }, [near]);

  useEffect(() => {
    if (!near) return;
    let objectUrl: string | null = null;
    let cancelled = false;
    const run = async () => {
      setFailed(false);
      const token = getToken();
      try {
        const res = await fetch(chatMediaUrl(name), {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (!res.ok || cancelled) {
          if (!cancelled) setFailed(true);
          return;
        }
        const next = URL.createObjectURL(await res.blob());
        if (cancelled) {
          URL.revokeObjectURL(next);
          return;
        }
        objectUrl = next;
        setUrl(next);
      } catch {
        if (!cancelled) setFailed(true);
      }
    };
    void run();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [name, tick, near]);

  if (failed) {
    return (
      <button type="button" className="mt-2 inline-flex min-h-11 items-center text-sm text-danger" onClick={() => setTick((n) => n + 1)}>
        بارگذاری نشد · تلاش دوباره
      </button>
    );
  }
  if (!url) return <div ref={holder} className="sozan-shimmer mt-2 h-40 w-full rounded-2xl" aria-hidden />;
  if (kind === "image") {
    return <img src={url} alt="" className="mt-2 max-h-80 w-full rounded-2xl border border-line/60 object-cover" />;
  }
  if (kind === "video") {
    return <video src={url} className="mt-2 max-h-80 w-full rounded-2xl border border-line/60" controls playsInline />;
  }
  return <audio src={url} className="mt-2 w-full" controls />;
}
