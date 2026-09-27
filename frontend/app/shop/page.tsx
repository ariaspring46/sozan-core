"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/app-shell";
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
type ThreadRow = { id: string; title: string; at?: number };
type ChatPayload = {
  notice?: string;
  threadId?: string;
  threads?: ThreadRow[];
};

export default function ShopPage() {
  const router = useRouter();
  const [shop, setShop] = useState<ShopState | null>(null);
  const [scan, setScan] = useState<ScanState | null>(null);
  const [build, setBuild] = useState<BuildLive | null>(null);
  const [busy, setBusy] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [viewTarget, setViewTarget] = useState("");
  const [viewPath, setViewPath] = useState("/");
  const [threadId, setThreadId] = useState("");
  const [threads, setThreads] = useState<ThreadRow[]>([]);
  const [previewKey, setPreviewKey] = useState(0);
  const [applyPatch, setApplyPatch] = useState<PreviewPatch | null>(null);
  const prevStatus = useRef("");
  const buildKey = useRef(emptyIdempotencySlot());
  const sendKey = useRef(emptyIdempotencySlot());

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
    void api<ChatPayload>("/chat")
      .then((data) => {
        setThreads(data.threads || []);
        if (data.threadId) setThreadId(data.threadId);
      })
      .catch(() => undefined);
  }, []);

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

  async function sendToChat() {
    const target = viewTarget.trim();
    if (!target || sending) return;
    setSending(true);
    setError("");
    setNotice("");
    const text = `این را عوض کن: ${target}`;
    const stamp = `${threadId}\0${viewPath}\0${target}`;
    const key = takeIdempotencyKey(sendKey.current, stamp);
    try {
      const data = await api<ChatPayload>("/chat", {
        method: "POST",
        headers: { "Idempotency-Key": key },
        body: JSON.stringify({
          text,
          viewPath,
          viewTarget: target,
          threadId,
        }),
      });
      finishIdempotencyKey(sendKey.current);
      if (data.threads) setThreads(data.threads);
      if (data.threadId) setThreadId(data.threadId);
      if (data.notice) {
        setNotice(data.notice);
        return;
      }
      router.push("/chat");
    } catch (err) {
      finishIdempotencyKey(sendKey.current, err);
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setSending(false);
    }
  }

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
        {error ? <p className="relative px-4 pt-3 text-sm text-danger">{error}</p> : null}
        {notice ? (
          <p className="relative px-4 pt-3 text-sm text-warm" role="status">
            {notice}
          </p>
        ) : null}
        {priceBlocked ? (
          <p className="relative px-4 pt-3 text-sm text-danger">
            بدون قیمت تومان ویترین فروش نمی‌شود.{" "}
            <a href="/more/inventory?focus=price" className="text-warm underline">
              ثبت قیمت
            </a>
          </p>
        ) : null}
        {scanNote ? (
          <p className={`relative px-4 pt-3 text-sm ${scan?.status === "error" ? "text-danger" : "text-warm"}`}>
            {scanNote}
          </p>
        ) : null}
        {viewTarget ? (
          <div className="relative flex flex-wrap items-center gap-2 px-4 pt-3">
            <p className="min-w-0 flex-1 truncate text-sm text-ink">{viewTarget}</p>
            {threads.length ? (
              <select
                className="max-w-[9rem] rounded-xl border border-line bg-canvas px-2 py-1 text-xs text-ink"
                value={threadId}
                onChange={(event) => setThreadId(event.target.value)}
                aria-label="گفتگو"
              >
                {threads.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.title}
                  </option>
                ))}
              </select>
            ) : null}
            <button
              type="button"
              className="shrink-0 rounded-xl border border-line px-2 py-1 text-xs text-warm disabled:opacity-50"
              disabled={sending}
              onClick={() => void sendToChat()}
            >
              فرستادن به چت
            </button>
          </div>
        ) : null}
        {/* پیش‌نمایش تقریباً کل صفحه را می‌گیرد؛ «باز کردن ویترین» در نوار بالای خود پیش‌نمایش است. */}
        <div className="relative flex min-h-0 flex-1 flex-col overflow-y-auto p-2 sm:p-3">
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
            onViewTarget={setViewTarget}
          />
        </div>
      </div>
    </AppShell>
  );
}
