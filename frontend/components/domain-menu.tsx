"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, ExternalLink, Globe } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export type ShopState = {
  brand: string;
  slug: string;
  port: number;
  domain: string;
  jobId: string;
  status: string;
  url: string;
  urlOk?: boolean;
  error?: string;
  publicHost?: string;
  cnameTarget?: string;
  cnameOk?: boolean;
  cnameCheck?: { detail?: string; status?: string };
  cnameSetup?: { ok?: boolean; error?: string };
  pendingBuild?: number;
};

function personalDomainValue(shop: ShopState | null) {
  const domain = String(shop?.domain || "").trim();
  const pub = String(shop?.publicHost || "").trim();
  if (!domain || domain === pub) return "";
  return domain.replace(/^https?:\/\//, "").replace(/\/.*$/, "");
}

export type BuildState = {
  jobId?: string;
  status?: string;
  step?: string;
  stepLabel?: string;
  url?: string;
  urlOk?: boolean;
  error?: string;
};

export function shopPublicUrl(shop: ShopState | null, fallback = "") {
  for (const raw of [shop?.publicHost, shop?.domain, shop?.url, fallback]) {
    const value = String(raw || "").trim();
    if (!value) continue;
    if (value.includes("127.0.0.1") || value.includes("localhost")) continue;
    return value.startsWith("http") ? value : `https://${value}`;
  }
  return "";
}

export function shopHostLabel(url: string) {
  try {
    return new URL(url).host;
  } catch {
    return url.replace(/^https?:\/\//, "");
  }
}

export function DomainMenu({
  shop,
  busy,
  onSaveDomain,
  onBuild,
}: {
  shop: ShopState | null;
  busy: boolean;
  onSaveDomain: (domain: string) => Promise<void>;
  onBuild: (rebuild?: boolean, reviseOnly?: boolean) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState(false);
  const [confirmRebuild, setConfirmRebuild] = useState(false);
  const [domain, setDomain] = useState(personalDomainValue(shop));
  const [mounted, setMounted] = useState(false);
  const live = shopPublicUrl(shop);
  const running = shop?.status === "running" || shop?.status === "queued";
  const label = running
    ? "در حال ساخت…"
    : shop?.status === "failed"
      ? "ساخت ناتمام"
      : live
        ? shopHostLabel(live)
        : "بعد از ساخت سایت";

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    setDomain(personalDomainValue(shop));
  }, [shop?.domain, shop?.publicHost]);

  const sheet = open ? (
    <div
      className="fixed inset-0 z-[80] bg-black/55 p-4 backdrop-blur-[2px]"
      onClick={() => {
        setConfirmRebuild(false);
        setOpen(false);
      }}
    >
      <div
        className="mx-auto mt-20 max-w-md space-y-4 rounded-3xl border border-line bg-paper p-5 shadow-card"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 className="text-lg font-bold">دامنه و انتشار</h2>
        <p className="text-sm leading-7 text-muted">
          {live
            ? "فروشگاه روی دامنهٔ سوزان زنده است. دامنهٔ شخصی را فقط وقتی بگذار که CNAME آن به نشانی زیر باشد."
            : running
              ? "کارخانه در حال ساخت است. پیشرفت را در چت می‌بینی."
              : "اول در چت سبک و رنگ را بگو، بعد بگو بساز. دامنه بعد از آماده شدن سایت است."}
        </p>
        {live ? (
          <a
            href={live}
            target="_blank"
            rel="noreferrer"
            className="flex min-h-11 items-center justify-center gap-2 rounded-xl bg-accent text-sm font-medium text-onAccent"
          >
            باز کردن فروشگاه
            <ExternalLink size={16} />
          </a>
        ) : null}
        <label className="block text-sm">دامنه شخصی</label>
        <Input
          dir="ltr"
          placeholder="shop.example.com"
          value={domain}
          onChange={(event) => setDomain(event.target.value)}
        />
        {shop?.cnameTarget ? (
          <p className="rounded-xl bg-canvas px-3 py-2 text-xs leading-6 text-muted" dir="ltr">
            CNAME → {shop.cnameTarget}
          </p>
        ) : null}
        {shop?.publicHost ? (
          <p className="text-xs leading-6 text-muted">
            نشانی سوزان: <span dir="ltr">{shop.publicHost}</span>
          </p>
        ) : null}
        {shop?.cnameCheck?.detail ? <p className="text-xs leading-6 text-warm">{shop.cnameCheck.detail}</p> : null}
        {shop?.cnameSetup?.error ? <p className="text-xs leading-6 text-danger">{shop.cnameSetup.error}</p> : null}
        <div className="flex flex-wrap gap-2">
          <Button type="button" disabled={busy} onClick={() => void onSaveDomain(domain).then(() => setOpen(false))}>
            ذخیره دامنه
          </Button>
          <Button
            type="button"
            variant="ghost"
            disabled={!live}
            onClick={() => {
              setOpen(false);
              setPreview(true);
            }}
          >
            پیش‌نمایش
          </Button>
          {live ? (
            confirmRebuild ? (
              <Button
                type="button"
                variant="ghost"
                disabled={busy}
                onClick={() => void onBuild(true).then(() => setOpen(false))}
              >
                تأیید ساخت دوباره
              </Button>
            ) : (
              <Button type="button" variant="ghost" disabled={busy} onClick={() => setConfirmRebuild(true)}>
                ساخت دوباره
              </Button>
            )
          ) : (
            <Button
              type="button"
              variant="ghost"
              disabled={busy || running}
              onClick={() => void onBuild(Boolean(shop?.slug)).then(() => setOpen(false))}
            >
              بساز
            </Button>
          )}
        </div>
        {confirmRebuild && live ? (
          <p className="text-sm text-warm">ساخت دوباره سایت زنده را از نو می‌سازد و چند دقیقه طول می‌کشد.</p>
        ) : null}
        {running ? (
          <p className="text-sm text-warm">در حال ساخت…</p>
        ) : shop?.status === "failed" ? (
          <p className="text-sm text-danger">{shop.error || "ساخت کامل نشد."}</p>
        ) : null}
      </div>
    </div>
  ) : null;

  const previewFrame =
    preview && live ? (
      <div className="fixed inset-0 z-[90] flex flex-col bg-paper">
        <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2">
          <p className="truncate text-sm" dir="ltr">
            {live}
          </p>
          <div className="flex gap-2">
            <a className="inline-flex min-h-11 items-center rounded-xl px-3 text-sm text-warm" href={live} target="_blank" rel="noreferrer">
              تب جدید
            </a>
            <Button type="button" variant="ghost" onClick={() => setPreview(false)}>
              بستن
            </Button>
          </div>
        </div>
        <iframe key={live} title="پیش‌نمایش فروشگاه" className="min-h-0 flex-1 bg-paper" src={live} />
      </div>
    ) : null;

  return (
    <>
      <div className="flex min-w-0 items-center gap-1">
        {live ? (
          <a
            href={live}
            target="_blank"
            rel="noreferrer"
            className="inline-flex max-w-[58vw] items-center gap-2 rounded-full border border-line bg-paper px-3 py-1.5 text-sm shadow-card"
          >
            <Globe size={16} />
            <span className="truncate">{label}</span>
            <ExternalLink size={14} className="shrink-0 text-muted" />
          </a>
        ) : (
          <button
            type="button"
            className="inline-flex max-w-[70vw] items-center gap-2 rounded-full border border-line bg-paper px-3 py-1.5 text-sm"
            onClick={() => {
              setDomain(personalDomainValue(shop));
              setOpen(true);
            }}
          >
            <Globe size={16} />
            <span className="truncate">{label}</span>
          </button>
        )}
        <button
          type="button"
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-line bg-paper text-muted"
          aria-label="تنظیم دامنه"
          onClick={() => {
            setDomain(personalDomainValue(shop));
            setOpen(true);
          }}
        >
          <ChevronDown size={16} />
        </button>
      </div>
      {mounted ? createPortal(
        <>
          {sheet}
          {previewFrame}
        </>,
        document.body,
      ) : null}
    </>
  );
}
