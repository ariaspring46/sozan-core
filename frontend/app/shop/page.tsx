"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { DomainMenu, shopPublicUrl, type ShopState } from "@/components/domain-menu";
import { ShopLiveBuild, type BuildLive, type PreviewPatch } from "@/components/shop-live-build";
import { ShopEditor, type ShopMsg, type ShopSelection } from "@/components/shop-editor";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
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
type ShopPayload = { shop: ShopState; scan?: ScanState; build?: BuildLive; messages?: ShopMsg[] };
type EditPayload = ShopPayload & {
  patched?: boolean;
  preview?: PreviewPatch;
  turn?: { rolledBack?: boolean; needsRebuild?: boolean };
};

function hasPatch(preview?: PreviewPatch | null) {
  return Boolean(preview && Object.keys(preview).length);
}

export default function ShopPage() {
  const [shop, setShop] = useState<ShopState | null>(null);
  const [scan, setScan] = useState<ScanState | null>(null);
  const [build, setBuild] = useState<BuildLive | null>(null);
  const [messages, setMessages] = useState<ShopMsg[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState("");
  const [selection, setSelection] = useState<ShopSelection | null>(null);
  const [viewPath, setViewPath] = useState("/");
  const [seekPath, setSeekPath] = useState("");
  const [clearPick, setClearPick] = useState(0);
  const [previewKey, setPreviewKey] = useState(0);
  const [applyPatch, setApplyPatch] = useState<PreviewPatch | null>(null);
  const prevStatus = useRef("");
  const buildKey = useRef(emptyIdempotencySlot());
  const editKey = useRef(emptyIdempotencySlot());

  const apply = (data: ShopPayload) => {
    setShop(data.shop);
    if (data.scan) setScan(data.scan);
    if (data.build) setBuild(data.build);
    if (data.messages) setMessages(data.messages);
  };

  const load = useCallback(async () => {
    const data = await api<ShopPayload>("/shop");
    apply(data);
    setLoadFailed(false);
  }, []);

  const firstLoad = useCallback(() => {
    setError("");
    void load()
      .catch((err) => {
        setError(err.message);
        setLoadFailed(true);
      })
      .finally(() => setLoaded(true));
  }, [load]);

  useEffect(() => {
    firstLoad();
  }, [firstLoad]);

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
      ? `در حال خواندن اینستاگرام ${scan.handles?.join("، ") || ""}…`
      : scan?.status === "error"
        ? (scan.error || "اسکن کانال کامل نشد.") +
          (importedCount ? ` ${importedCount} کالای قبلی سر جایش است.` : "")
        : scan?.needsReview
          ? importedCount
            ? `${importedCount} کالا وارد شد؛ عکس کم است.`
            : scan.kept
              ? `چیزی تازه خوانده نشد؛ ${scan.kept} کالای قبلی سر جایش است.`
              : "چیزی از این صفحه خوانده نشد."
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

  const clearSelection = useCallback(() => {
    setSelection(null);
    setClearPick((value) => value + 1);
  }, []);

  /** یک دستور ویرایش به ویرایشگر زندهٔ فروشگاه؛ پیش‌نمایش بدون رفتن به چت به‌روز می‌شود. */
  const runEdit = useCallback(
    async (text: string, opts?: { target?: string; viewPath?: string }) => {
      const target = (opts?.target || "").trim();
      const path = opts?.viewPath || viewPath;
      setEditing(true);
      setError("");
      const stamp = `${path}\0${target}\0${text}`;
      const key = takeIdempotencyKey(editKey.current, stamp);
      try {
        const data = await api<EditPayload>("/shop/chat", {
          method: "POST",
          headers: { "Idempotency-Key": key },
          body: JSON.stringify({ text, viewPath: path, viewTarget: target }),
        });
        finishIdempotencyKey(editKey.current);
        apply(data);
        const preview = data.preview || null;
        if (preview?.viewPath) setSeekPath(preview.viewPath);
        if (hasPatch(preview)) setApplyPatch({ ...preview });
        if (data.patched && preview?.find && preview.replace && selection && selection.text === preview.find) {
          setSelection({ ...selection, text: preview.replace });
        } else if (data.patched && target) {
          clearSelection();
        }
        return true;
      } catch (err) {
        finishIdempotencyKey(editKey.current, err);
        setError(err instanceof Error ? err.message : "تغییر انجام نشد.");
        return false;
      } finally {
        setEditing(false);
      }
    },
    [viewPath, selection, clearSelection],
  );

  return (
    <AppShell
      header={
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0 flex-1">
            <p className="flex items-center gap-2 text-sm text-muted">
              فروشگاه
              {building ? <span className="sozan-breathe h-1.5 w-1.5 rounded-full bg-signal" /> : null}
            </p>
            <h1 dir="auto" className="truncate text-lg font-bold">
              {shop?.brand || "فروشگاه"}
            </h1>
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
      <div className={cn("relative flex h-full min-h-0 flex-col lg:flex-row", building ? "sozan-aurora" : "")}>
        <div className="relative flex min-h-0 flex-1 flex-col">
          {error ? (
            <p className="relative px-3 pt-2 text-sm text-danger" role="alert">
              {error}
            </p>
          ) : null}
          {priceBlocked ? (
            <p className="relative px-3 pt-2 text-sm text-danger">
              بدون قیمت تومان ویترین فروش نمی‌شود.{" "}
              <Link href="/more/inventory?focus=price" className="inline-flex min-h-11 items-center text-warm underline">
                ثبت قیمت
              </Link>
            </p>
          ) : null}
          {scanNote ? (
            <p className={`relative px-3 pt-2 text-sm ${scan?.status === "error" ? "text-danger" : "text-warm"}`}>{scanNote}</p>
          ) : null}
          {/* پیش‌نمایش تقریباً کل صفحه را می‌گیرد؛ «باز کردن ویترین» در نوار بالای خود پیش‌نمایش است. */}
          <div className="relative flex min-h-0 flex-1 flex-col overflow-y-auto p-2 sm:p-3">
            {loaded && loadFailed && !shop ? (
              <EmptyState
                title="فروشگاه بالا نیامد"
                detail="اینترنت یا سرور جواب نداد. فروشگاهت سر جایش است؛ چند لحظه بعد دوباره امتحان کن."
                action={
                  <Button type="button" onClick={firstLoad}>
                    دوباره امتحان کن
                  </Button>
                }
              />
            ) : null}
            {loaded && !loadFailed && !live && !building && !build?.status ? (
              <EmptyState
                title="هنوز سایت فروشگاه ساخته نشده"
                detail="در چت بگو چه حسی و چه رنگی می‌خواهی؛ بعد همین‌جا می‌سازم و هر بخشش را ویرایش می‌کنی."
                action={
                  <div className="flex flex-wrap justify-center gap-2">
                    <Link href="/chat" className="inline-flex min-h-11 items-center rounded-xl border border-line px-4 text-sm text-warm">
                      رفتن به چت
                    </Link>
                    <Button type="button" disabled={busy} onClick={() => void runBuild()}>
                      {busy ? "در حال شروع…" : "ساخت سایت"}
                    </Button>
                  </div>
                }
              />
            ) : null}
            <ShopLiveBuild
              build={build}
              href={shopPublic}
              previewKey={previewKey}
              pendingBuild={Number(shop?.pendingBuild || 0)}
              buildBusy={busy || building}
              applyPatch={applyPatch}
              onBuild={() => void runBuild(true, true)}
              onRetry={() => void runBuild(true, true)}
              onViewPath={setViewPath}
              onViewTarget={(text, tag) => {
                const clean = text.trim();
                if (clean || tag) setSelection({ text: clean, tag: tag || "" });
              }}
              seekPath={seekPath}
              clearPick={clearPick}
            />
          </div>
        </div>
        {live && shopPublic ? (
          <aside
            aria-label="ویرایش فروشگاه"
            className="relative flex max-h-[50%] shrink-0 flex-col overflow-y-auto border-t border-line bg-paper px-3 pb-2 pt-2 lg:max-h-none lg:w-[22rem] lg:border-s lg:border-t-0 lg:px-4 lg:pt-3"
          >
            <ShopEditor
              brand={shop?.brand || ""}
              hidePrices={Boolean(shop?.hidePrices)}
              pending={Number(shop?.pendingBuild || 0)}
              busy={editing}
              buildBusy={busy || building}
              selection={selection}
              messages={messages}
              onRun={runEdit}
              onPublish={() => void runBuild(true, true)}
              onClearSelection={clearSelection}
            />
          </aside>
        ) : null}
      </div>
    </AppShell>
  );
}
