"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { ChatNav } from "@/components/chat-nav";
import { DomainMenu, shopPublicUrl, type ShopState } from "@/components/domain-menu";
import { ShopLiveBuild, type BuildLive, type PreviewPatch } from "@/components/shop-live-build";
import { api } from "@/lib/api";
import { emptyIdempotencySlot, finishIdempotencyKey, takeIdempotencyKey } from "@/lib/idempotency";
import { cn } from "@/lib/utils";

type ScanState = {
  status?: string;
  productCount?: number;
  error?: string;
  handles?: string[];
  needsReview?: boolean;
  errorClass?: string;
  imported?: number;
  kept?: number;
  noImage?: number;
  noPrice?: number;
  rejected?: number;
};
type ShopPayload = { shop: ShopState; scan?: ScanState; build?: BuildLive };

export default function ShopPage() {
  const [shop, setShop] = useState<ShopState | null>(null);
  const [scan, setScan] = useState<ScanState | null>(null);
  const [build, setBuild] = useState<BuildLive | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [viewTarget, setViewTarget] = useState("");
  const [previewKey, setPreviewKey] = useState(0);
  const [applyPatch, setApplyPatch] = useState<PreviewPatch | null>(null);
  const prevStatus = useRef("");
  const buildKey = useRef(emptyIdempotencySlot());

  const apply = (data: ShopPayload) => {
    setShop(data.shop);
    if (data.scan) setScan(data.scan);
    if (data.build) setBuild(data.build);
  };

  const load = useCallback(async () => {
    const data = await api<ShopPayload>("/shop");
    apply(data);
  }, []);

  useEffect(() => {
    void load().catch((err) => setError(err.message));
  }, [load]);

  useEffect(() => {
    const status = shop?.status || build?.status || "";
    if (prevStatus.current === "running" && status === "ready") {
      setPreviewKey((value) => value + 1);
    }
    prevStatus.current = status;
  }, [shop?.status, build?.status]);

  const building = Boolean(
    shop && (shop.status === "running" || shop.status === "queued" || build?.status === "running" || build?.status === "queued"),
  );
  const scanning = scan?.status === "running";

  useEffect(() => {
    if (!building && !scanning) return;
    const timer = window.setInterval(() => {
      void load().catch(() => undefined);
    }, building || scanning ? 1600 : 800);
    return () => window.clearInterval(timer);
  }, [building, scanning, load]);

  const importedCount = scan?.imported || scan?.productCount || 0;
  const scanNote =
    scan?.status === "running"
      ? `در حال خواندن اینستاگرام ${scan.handles?.join("، ") || ""}… کالاها به فروش می‌آیند.`
      : scan?.status === "error"
        ? (scan.error || "اسکن کانال کامل نشد.") +
          (importedCount ? ` ${importedCount} کالای قبلی سر جایش است.` : "") +
          " برای تلاش دوباره، همان آدرس را در چت بفرست."
        : scan?.needsReview && importedCount
          ? `${importedCount} کالا وارد شد؛ عکس کم است، بعداً عکس بگذار.`
          : scan?.needsReview
            ? scan.kept
              ? `چیزی تازه از این صفحه خوانده نشد؛ ${scan.kept} کالای قبلی سر جایش است.`
              : "چیزی از این صفحه خوانده نشد؛ دوباره اسکن کن یا کالا را دستی اضافه کن."
            : scan?.status === "done" && importedCount
              ? `${importedCount} کالا وارد شد` +
                (scan.rejected ? `، ${scan.rejected} رد` : "") +
                (scan.noImage ? `، ${scan.noImage} بدون عکس` : "") +
                (scan.noPrice ? `، ${scan.noPrice} بدون قیمت — قبل از ساخت سایت قیمت بگذار یا بگو قیمت‌ها را مخفی کن` : "") +
                "."
              : "";
  const priceBlocked = Boolean(shop?.priceBlocked && !shop?.hidePrices);
  const shopPublic = shopPublicUrl(shop, build?.url);
  const live = Boolean(
    shop && (shop.status === "ready" || (shop.slug && (shop.url || shop.publicHost || shop.port))),
  );

  const runBuild = useCallback(async (rebuild?: boolean, reviseOnly?: boolean) => {
    setBusy(true);
    setError("");
    const prompt = reviseOnly ? shop?.brand || "" : rebuild ? "از نو بساز" : shop?.brand || "";
    const stamp = `${rebuild ? "1" : "0"}:${reviseOnly ? "1" : "0"}:${prompt}`;
    const key = takeIdempotencyKey(buildKey.current, stamp);
    try {
      const data = await api<ShopPayload & { result?: { error?: string } }>("/shop/build", {
        method: "POST",
        headers: { "Idempotency-Key": key },
        body: JSON.stringify({
          prompt,
          rebuild: Boolean(rebuild),
          reviseOnly: Boolean(reviseOnly),
        }),
      });
      apply(data);
      setApplyPatch(null);
      finishIdempotencyKey(buildKey.current);
      if (data.result?.error) setError(data.result.error);
    } catch (err) {
      finishIdempotencyKey(buildKey.current, err);
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setBusy(false);
    }
  }, [shop?.brand]);

  return (
    <AppShell
      header={
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="flex items-center gap-2 text-sm text-muted">
              فروشگاه
              {building ? <span className="sozan-breathe h-1.5 w-1.5 rounded-full bg-signal" /> : null}
            </p>
            <h1 className="truncate text-lg font-bold">{shop?.brand || "فروشگاه"}</h1>
          </div>
          <DomainMenu
            shop={shop}
            busy={busy}
            onSaveDomain={async (domain) => {
              const data = await api<ShopPayload>("/shop/domain", {
                method: "PATCH",
                body: JSON.stringify({ domain }),
              });
              apply(data);
            }}
            onBuild={runBuild}
          />
        </div>
      }
    >
      <div className={cn("relative flex h-full flex-col", building ? "sozan-aurora" : "")}>
        <div className="px-4 pt-3">
          <ChatNav current="shop" />
        </div>
        {error ? <p className="relative px-4 pt-3 text-sm text-danger">{error}</p> : null}
        {priceBlocked ? (
          <div className="relative mx-4 mt-3 rounded-2xl border border-danger/40 bg-danger/10 px-4 py-3">
            <p className="text-sm font-bold text-danger">بدون قیمت تومان، ویترین فروش نمی‌شود — فقط استعلام.</p>
            <a href="/more/inventory?focus=price" className="mt-2 inline-flex text-sm text-warm underline">
              ثبت قیمت
            </a>
          </div>
        ) : null}
        {scanNote ? (
          <p className={`relative px-4 pt-3 text-sm ${scan?.status === "error" ? "text-danger" : "text-warm"}`}>
            {scanNote}
          </p>
        ) : null}
        <p className="relative px-4 pt-3 text-sm text-warm">
          {viewTarget ? (
            <Link href="/chat">برای عوض کردن «{viewTarget}» در چت بگو</Link>
          ) : (
            <Link href="/chat">{live ? "ادیت و ساخت در چت" : "در چت بگو چه فروشگاهی می‌خواهی"}</Link>
          )}
        </p>
        {live && shopPublic ? (
          <a href={shopPublic} target="_blank" rel="noreferrer" className="relative px-4 pt-2 text-sm text-warm underline">
            باز کردن ویترین
          </a>
        ) : null}
        <div className="relative min-h-0 flex-1 overflow-y-auto px-4 py-3">
          <ShopLiveBuild
            build={build}
            href={shopPublic}
            previewKey={previewKey}
            pendingBuild={Number(shop?.pendingBuild || 0)}
            buildBusy={busy || building}
            applyPatch={applyPatch}
            onBuild={() => void runBuild(true, true)}
            onRetry={() => void runBuild(true, true)}
            onViewTarget={setViewTarget}
          />
        </div>
      </div>
    </AppShell>
  );
}
