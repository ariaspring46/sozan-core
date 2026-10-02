"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type AlertAccount = { id: string; platform: string; label?: string; handle?: string; needsReconnect?: boolean };

const PLATFORM_FA: Record<string, string> = {
  instagram: "اینستاگرام",
  telegram: "تلگرام",
  whatsapp: "واتساپ",
  bale: "بله",
  rubika: "روبیکا",
};

/** نوار هشدار وقتی یکی از کانال‌ها قطع است؛ پیام تازه نمی‌آید و پاسخ خودکار کار نمی‌کند. */
export function ChannelAlert({ inset = true }: { inset?: boolean }) {
  const [broken, setBroken] = useState<AlertAccount[]>([]);

  useEffect(() => {
    let cancelled = false;
    void api<{ accounts?: AlertAccount[] }>("/channels")
      .then((data) => {
        if (cancelled) return;
        setBroken((data.accounts || []).filter((row) => row && row.needsReconnect));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  if (!broken.length) return null;
  const first = broken[0];
  const name = PLATFORM_FA[first.platform] || first.label || "کانال";
  const handle = first.handle ? ` (${first.handle.replace(/^@?/, "@")})` : "";
  return (
    <div role="alert" className={`${inset ? "mx-3 mt-3 sm:mx-4" : ""} flex items-center gap-3 rounded-2xl border border-danger/50 bg-danger/10 px-4 py-3 text-sm`}>
      <p className="min-w-0 flex-1 leading-6 text-ink">
        اتصال {name}
        <bdi dir="ltr">{handle}</bdi> قطع است؛ پیام تازهٔ مشتری نمی‌رسد و پاسخ خودکار کار نمی‌کند.
        {broken.length > 1 ? ` (${broken.length.toLocaleString("fa-IR")} کانال)` : ""}
      </p>
      <Link href="/more/channels" className="inline-flex min-h-11 shrink-0 items-center rounded-xl bg-accentStrong px-3 text-sm font-bold text-onAccent">
        اتصال دوباره
      </Link>
    </div>
  );
}
