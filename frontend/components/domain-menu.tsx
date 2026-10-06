"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, ExternalLink, Globe, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useBackClose } from "@/lib/back-stack";

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
  /** چند تغییر هنوز با «برگشت» پس گرفتنی است؛ بعد از هر بیلد ۰ می‌شود. */
  undoDepth?: number;
  hidePrices?: boolean;
  priceBlocked?: boolean;
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

/** آدرس عمومی فقط دامنه است؛ IP، پورت و نشانی‌های داخلی هرگز به فروشنده نشان داده نمی‌شوند. */
function publicUrlOrNull(raw: string | undefined | null): string {
  const value = String(raw || "").trim();
  if (!value) return "";
  const href = value.startsWith("http") ? value : `https://${value}`;
  try {
    const url = new URL(href);
    const host = url.hostname.toLowerCase();
    if (!host) return "";
    if (/(^|\.)localhost$/.test(host)) return "";
    if (/^(\d{1,3}\.){3}\d{1,3}$/.test(host)) return "";
    if (host.includes(":")) return "";
    if (/\.(local|internal)$/.test(host)) return "";
    return `https://${host}`;
  } catch {
    return "";
  }
}

export function shopPublicUrl(shop: ShopState | null, fallback = "") {
  for (const raw of [shop?.publicHost, shop?.domain, shop?.url, fallback]) {
    const found = publicUrlOrNull(raw);
    if (found) return found;
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
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saved, setSaved] = useState(false);
  const live = shopPublicUrl(shop);
  const running = shop?.status === "running" || shop?.status === "queued";
  const hostLabel = Boolean(live) && !running && shop?.status !== "failed";
  const label = running
    ? "در حال ساخت…"
    : shop?.status === "failed"
      ? "ساخت کامل نشد"
      : live
        ? shopHostLabel(live)
        : "بعد از ساخت سایت";
  // نشانی سوزان بدون پسوند کوتاه نشان داده می‌شود؛ دامنهٔ شخصی کامل.
  const shortLabel = hostLabel ? label.replace(/\.sozan-core\.ir$/i, "") : label;

  useEffect(() => {
    setMounted(true);
  }, []);

  /** خطای سرور (دامنهٔ نامعتبر، دامنهٔ دیگران، قطع شبکه) داخل همین کادر دیده می‌شود، نه بی‌صدا بسته‌شدن. */
  async function saveDomain() {
    setSaveError("");
    setSaved(false);
    setSaving(true);
    try {
      await onSaveDomain(domain.trim());
      if (domain.trim()) setSaved(true);
      else setOpen(false);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "ذخیره نشد. دوباره امتحان کن.");
    } finally {
      setSaving(false);
    }
  }

  useEffect(() => {
    setDomain(personalDomainValue(shop));
  }, [shop?.domain, shop?.publicHost]);

  useEffect(() => {
    if (!open && !preview) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setConfirmRebuild(false);
      setOpen(false);
      setPreview(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, preview]);

  useBackClose(open, () => {
    setConfirmRebuild(false);
    setOpen(false);
  });
  useBackClose(Boolean(preview && live), () => setPreview(false));

  const sheet = open ? (
    <div
      className="fixed inset-0 z-[80] flex items-end justify-center bg-black/55 backdrop-blur-[2px] sm:items-center sm:p-4"
      onClick={() => {
        setConfirmRebuild(false);
        setOpen(false);
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="دامنه و انتشار"
        className="max-h-[92dvh] w-full max-w-md space-y-4 overflow-y-auto overscroll-contain rounded-t-3xl border border-line bg-paper p-5 pb-[max(1.25rem,env(safe-area-inset-bottom))] shadow-card sm:rounded-3xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-bold">دامنه و انتشار</h2>
          <button
            type="button"
            aria-label="بستن"
            className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-muted hover:bg-canvas"
            onClick={() => {
              setConfirmRebuild(false);
              setOpen(false);
            }}
          >
            <X size={20} aria-hidden />
          </button>
        </div>
        <p className="text-sm leading-7 text-muted">
          {live
            ? "فروشگاه روی دامنهٔ سوزان زنده است. دامنهٔ شخصی را وقتی بگذار که در پنل دامنه‌ات یک رکورد CNAME به نشانی زیر ساخته باشی."
            : running
              ? "سوزان در حال ساخت سایت است. پیشرفت را در چت می‌بینی."
              : "اول در چت سبک و رنگ را بگو، بعد بگو بساز. دامنه بعد از آماده شدن سایت است."}
        </p>
        {live ? (
          <a
            href={live}
            target="_blank"
            rel="noreferrer"
            className="flex min-h-11 items-center justify-center gap-2 rounded-xl bg-accentStrong text-sm font-medium text-onAccent"
          >
            باز کردن فروشگاه
            <ExternalLink size={16} />
          </a>
        ) : null}
        <label className="block text-sm" htmlFor="shop-domain">دامنهٔ شخصی (اختیاری)</label>
        <Input
          id="shop-domain"
          dir="ltr"
          placeholder="shop.example.com"
          inputMode="url"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          enterKeyHint="done"
          value={domain}
          onChange={(event) => setDomain(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void saveDomain();
            }
          }}
        />
        {shop?.cnameTarget ? (
          <p className="wrap-any rounded-xl bg-canvas px-3 py-2 text-sm leading-6 text-muted" dir="ltr">
            CNAME → {shop.cnameTarget}
          </p>
        ) : null}
        {shop?.publicHost ? (
          <p className="wrap-any text-sm leading-6 text-muted">
            نشانی سوزان: <bdi dir="ltr">{shop.publicHost}</bdi>
          </p>
        ) : null}
        {shop?.cnameCheck?.detail ? <p className="text-sm leading-6 text-warm">{shop.cnameCheck.detail}</p> : null}
        {shop?.cnameSetup?.error ? <p className="text-sm leading-6 text-danger" role="alert">{shop.cnameSetup.error}</p> : null}
        {saveError ? (
          <p className="text-sm leading-6 text-danger" role="alert">
            {saveError}
          </p>
        ) : null}
        {saved ? (
          <p className="text-sm leading-6 text-warm" role="status">
            ذخیره شد. رکورد CNAME بالا را در پنل دامنه‌ات بگذار؛ وقتی DNS رسید وضعیت «درست» می‌شود.
          </p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <Button type="button" disabled={busy || saving} onClick={() => void saveDomain()}>
            {saving ? "در حال ذخیره…" : "ذخیره دامنه"}
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
              disabled={busy || running || Boolean(shop?.priceBlocked)}
              onClick={() => void onBuild(Boolean(shop?.slug)).then(() => setOpen(false))}
            >
              بساز
            </Button>
          )}
        </div>
        {confirmRebuild && live ? (
          <p className="text-sm text-warm">ساخت دوباره سایت زنده را از نو می‌سازد و چند دقیقه طول می‌کشد.</p>
        ) : null}
        {shop?.priceBlocked ? (
          <div className="space-y-2">
            <p className="text-sm text-warm">
              هنوز کالایی بدون قیمت تومان مانده؛ کالای بی‌قیمت در ویترین فقط «استعلام» می‌شود و خرید نمی‌رود. قیمت‌ها را در انبار بگذار و دوباره بساز.
            </p>
            <a
              href="/more/inventory?focus=price"
              className="inline-flex min-h-11 items-center rounded-xl bg-accentStrong px-4 text-sm font-bold text-onAccent"
            >
              انبار و قیمت‌گذاری
            </a>
          </div>
        ) : running ? (
          <p className="text-sm text-warm">در حال ساخت…</p>
        ) : shop?.status === "failed" ? (
          <div className="space-y-2">
            <p className="text-sm text-danger">{shop.error || "ساخت کامل نشد."}</p>
            <Button type="button" variant="ghost" disabled={busy} onClick={() => void onBuild(Boolean(shop?.slug))}>
              دوباره بساز
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  ) : null;

  const previewFrame =
    preview && live ? (
      <div className="fixed inset-x-0 top-0 z-[90] flex h-dvh flex-col bg-paper">
        <div className="flex items-center justify-between gap-2 border-b border-line px-3 pb-2 pt-[max(0.5rem,env(safe-area-inset-top))]">
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
      <button
        type="button"
        className="inline-flex min-h-11 max-w-[46vw] shrink-0 items-center gap-2 rounded-full border border-line bg-paper px-3 text-sm shadow-card sm:max-w-[58vw]"
        aria-label={hostLabel ? `دامنه و انتشار؛ آدرس فروشگاه ${label}` : `دامنه و انتشار؛ ${label}`}
        onClick={() => {
          setDomain(personalDomainValue(shop));
          setSaveError("");
          setSaved(false);
          setOpen(true);
        }}
      >
        <Globe size={16} className="shrink-0" aria-hidden />
        <span className="truncate" dir={hostLabel ? "ltr" : undefined}>
          {shortLabel}
        </span>
        <ChevronDown size={16} className="shrink-0 text-muted" aria-hidden />
      </button>
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
