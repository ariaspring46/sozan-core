"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Hammer, Undo2 } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { DomainMenu, shopPublicUrl, type ShopState } from "@/components/domain-menu";
import { ShopLiveBuild, type BuildLive, type PreviewPatch } from "@/components/shop-live-build";
import { ShopEditor, friendlyReply, selectionPhoto, type ShopMsg, type ShopSelection } from "@/components/shop-editor";
import { ConfirmCard } from "@/components/chat-parts";
import { ShopEditSheet } from "@/components/shop-edit-sheet";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { emptyIdempotencySlot, finishIdempotencyKey, takeIdempotencyKey } from "@/lib/idempotency";
import { shrinkImage } from "@/lib/image-shrink";
import { useMediaQuery } from "@/lib/use-media";
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
  reply?: string;
  turn?: { rolledBack?: boolean; needsRebuild?: boolean };
  /** «از نو بساز» تایپ‌شده: سایت را عوض نکرد و تأیید خواست. */
  needsConfirm?: boolean;
};
type EditOutcome = { ok: boolean; patched: boolean; reply: string };

function lastReply(rows?: ShopMsg[]) {
  const row = [...(rows || [])].reverse().find((item) => item.role === "assistant" && item.text?.trim());
  return row ? row.text : "";
}

/** دو دکمهٔ پایین پیش‌نمایش موبایل: «بیلد» سایت را با تغییرها می‌سازد، «برگشت» یک تغییر را پس می‌گیرد؛ بعد از بیلد برگشت قفل می‌شود. */
function ShopActionBar({
  pending,
  undoDepth,
  working,
  building,
  failed,
  onBuild,
  onUndo,
}: {
  pending: number;
  undoDepth: number;
  working: boolean;
  building: boolean;
  failed: boolean;
  onBuild: () => void;
  onUndo: () => void;
}) {
  const canBuild = !working && (pending > 0 || failed);
  const canUndo = !working && undoDepth > 0;
  return (
    <div className="flex shrink-0 gap-2 border-t border-line bg-paper px-3 py-2" role="group" aria-label="بیلد و برگشت">
      <button
        type="button"
        onClick={onBuild}
        disabled={!canBuild}
        className={cn(
          "inline-flex min-h-12 flex-1 items-center justify-center gap-2 rounded-xl px-4 text-[15px] font-bold",
          canBuild ? "bg-accentStrong text-onAccent" : "border border-line bg-canvas text-muted",
        )}
      >
        <Hammer size={18} aria-hidden />
        {building ? "در حال بیلد…" : failed ? "بیلد دوباره" : "بیلد"}
        {pending > 0 && !building ? (
          <span className="rounded-full bg-onAccent/20 px-2 text-sm leading-6">{pending.toLocaleString("fa-IR")}</span>
        ) : null}
      </button>
      <button
        type="button"
        onClick={onUndo}
        disabled={!canUndo}
        className={cn(
          "inline-flex min-h-12 flex-1 items-center justify-center gap-2 rounded-xl border px-4 text-[15px] font-bold",
          canUndo ? "border-accent/50 bg-paper text-warm" : "border-line bg-canvas text-muted",
        )}
      >
        <Undo2 size={18} aria-hidden />
        برگشت
      </button>
    </div>
  );
}

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
  const [sheetOpen, setSheetOpen] = useState(false);
  const [sheetReply, setSheetReply] = useState("");
  const [sheetError, setSheetError] = useState("");
  const [undoing, setUndoing] = useState(false);
  const [notice, setNotice] = useState("");
  const [rebuildAsk, setRebuildAsk] = useState<{ text: string; command: string } | null>(null);
  const isMobile = useMediaQuery("(max-width: 1023px)");
  const prevStatus = useRef("");
  const buildKey = useRef(emptyIdempotencySlot());
  const editKey = useRef(emptyIdempotencySlot());
  const undoKey = useRef(emptyIdempotencySlot());

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
      setNotice("فروشگاه ساخته شد و همین حالا زنده است.");
    }
    prevStatus.current = status;
  }, [shop?.status, build?.status]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 5000);
    return () => window.clearTimeout(timer);
  }, [notice]);

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
  const unpriced = shop?.hidePrices ? 0 : Number(shop?.unpriced || 0);
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

  const closeSheet = useCallback(() => {
    setSheetOpen(false);
    setSheetError("");
    setSheetReply("");
    clearSelection();
  }, [clearSelection]);

  /** یک دستور ویرایش به ویرایشگر زندهٔ فروشگاه؛ پیش‌نمایش بدون رفتن به چت به‌روز می‌شود. */
  const runEdit = useCallback(
    async (text: string, opts?: { target?: string; viewPath?: string; confirm?: boolean }): Promise<EditOutcome> => {
      const target = (opts?.target || "").trim();
      const path = opts?.viewPath || viewPath;
      setEditing(true);
      setError("");
      setSheetError("");
      const stamp = `${path}\0${target}\0${text}\0${opts?.confirm ? "1" : ""}`;
      const key = takeIdempotencyKey(editKey.current, stamp);
      try {
        const data = await api<EditPayload>("/shop/chat", {
          method: "POST",
          headers: { "Idempotency-Key": key },
          body: JSON.stringify({ text, viewPath: path, viewTarget: target, ...(opts?.confirm ? { confirm: true } : {}) }),
        });
        finishIdempotencyKey(editKey.current);
        apply(data);
        if (data.needsConfirm) {
          setRebuildAsk({ text: lastReply(data.messages), command: text });
          if (isMobile) closeSheet();
          return { ok: true, patched: false, reply: "" };
        }
        setRebuildAsk(null);
        const preview = data.preview || null;
        if (preview?.viewPath) setSeekPath(preview.viewPath);
        if (hasPatch(preview)) setApplyPatch({ ...preview, seq: Number(data.shop?.undoDepth || 0) });
        const reply = lastReply(data.messages);
        if (isMobile) {
          if (data.patched) {
            closeSheet();
            setNotice(reply);
          } else {
            setSheetReply(reply);
          }
        } else if (data.patched && preview?.find && preview.replace && selection && selection.text === preview.find) {
          setSelection({ ...selection, text: preview.replace });
        } else if (data.patched && target) {
          clearSelection();
        }
        return { ok: true, patched: Boolean(data.patched), reply };
      } catch (err) {
        finishIdempotencyKey(editKey.current, err);
        const message = err instanceof Error ? err.message : "تغییر انجام نشد.";
        if (isMobile) setSheetError(message);
        else setError(message);
        return { ok: false, patched: false, reply: "" };
      } finally {
        setEditing(false);
      }
    },
    [viewPath, selection, clearSelection, closeSheet, isMobile],
  );

  /** «برگشت»: آخرین تغییر بیلدنشده را پس می‌گیرد. */
  const undo = useCallback(async () => {
    setUndoing(true);
    setError("");
    const key = takeIdempotencyKey(undoKey.current, `undo:${shop?.undoDepth ?? 0}`);
    try {
      const data = await api<EditPayload>("/shop/undo", {
        method: "POST",
        headers: { "Idempotency-Key": key },
        body: JSON.stringify({}),
      });
      finishIdempotencyKey(undoKey.current);
      apply(data);
      if (data.patched) setApplyPatch({ undo: true, to: Number(data.shop?.undoDepth || 0) });
      closeSheet();
      setNotice(data.reply || "");
    } catch (err) {
      finishIdempotencyKey(undoKey.current, err);
      setError(err instanceof Error ? err.message : "برگشت انجام نشد.");
    } finally {
      setUndoing(false);
    }
  }, [shop?.undoDepth, closeSheet]);

  /** عکس انتخاب‌شده را با عکس گوشی عوض می‌کند. */
  const replaceImage = useCallback(
    async (file: File) => {
      const photo = selection ? selectionPhoto(selection) : null;
      if (!selection || !photo) return false;
      setEditing(true);
      setSheetError("");
      try {
        const small = await shrinkImage(file);
        const body = new FormData();
        body.append("file", small);
        body.append("src", photo.src);
        if (selection.product) body.append("product", selection.product);
        const data = await api<EditPayload>("/shop/image", { method: "POST", body });
        apply(data);
        setApplyPatch({ reload: true, seq: Number(data.shop?.undoDepth || 0) });
        closeSheet();
        setNotice(data.reply || "عکس عوض شد.");
        return true;
      } catch (err) {
        setSheetError(err instanceof Error ? err.message : "عکس عوض نشد.");
        return false;
      } finally {
        setEditing(false);
      }
    },
    [selection, closeSheet],
  );

  const onPick = useCallback(
    (picked: ShopSelection, longPress: boolean) => {
      const clean = { ...picked, text: picked.text.trim() };
      if (!clean.text && !clean.tag && !clean.src && !clean.image) return;
      setSelection(clean);
      if (isMobile && longPress) {
        setNotice("");
        setSheetReply("");
        setSheetError("");
        setSheetOpen(true);
      }
    },
    [isMobile],
  );

  const pending = Number(shop?.pendingBuild || 0);
  const working = busy || building || editing || undoing;
  const mobilePreview = isMobile && live && Boolean(shopPublic);

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
          {unpriced > 0 ? (
            <p className="relative px-3 pt-2 text-sm text-muted">
              {unpriced.toLocaleString("fa-IR")} کالا بی‌قیمت است و در ویترین «استعلام قیمت» نشان می‌دهد.{" "}
              <Link href="/more/inventory?focus=price" className="inline-flex min-h-11 items-center text-warm underline">
                ثبت قیمت
              </Link>
            </p>
          ) : null}
          {scanNote ? (
            <p className={`relative px-3 pt-2 text-sm ${scan?.status === "error" ? "text-danger" : "text-warm"}`}>{scanNote}</p>
          ) : null}
          {/* موبایل: فقط خود سایت، بدون چت؛ ویرایش با نگه داشتن انگشت روی هر بخش. دسکتاپ: پیش‌نمایش + ویرایشگر کنارش. */}
          <div className={cn("relative flex min-h-0 flex-1 flex-col overflow-y-auto", mobilePreview ? "p-0" : "p-2 sm:p-3")}>
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
              pendingBuild={pending}
              buildBusy={busy || building}
              applyPatch={applyPatch}
              onBuild={() => void runBuild(true, true)}
              onRetry={() => void runBuild(true, true)}
              onViewPath={setViewPath}
              onPick={onPick}
              seekPath={seekPath}
              clearPick={clearPick}
              compact={mobilePreview}
            />
            {notice ? (
              <p
                className="pointer-events-none absolute inset-x-3 top-3 z-30 rounded-2xl border border-accent/30 bg-paper/95 px-4 py-3 text-sm leading-7 text-ink shadow-card"
                role="status"
              >
                {friendlyReply(notice)}
              </p>
            ) : null}
            {rebuildAsk ? (
              <div className="absolute inset-x-3 bottom-3 z-40">
                <ConfirmCard
                  tool="shop_chat"
                  text={rebuildAsk.text}
                  open
                  busy={editing || busy}
                  onConfirm={() => {
                    const command = rebuildAsk.command;
                    setRebuildAsk(null);
                    void runEdit(command, { confirm: true });
                  }}
                  onCancel={() => setRebuildAsk(null)}
                />
              </div>
            ) : null}
            {mobilePreview && sheetOpen && selection ? (
              <>
                {/* با pointerdown می‌بندد نه click: انگشتی که هنوز بعد از «نگه داشتن» روی صفحه است وقتی بلند شود، روی این پرده click می‌سازد و برگه را همان لحظه می‌بست. */}
                <button type="button" aria-label="بستن ویرایش" tabIndex={-1} className="absolute inset-0 z-20 cursor-default" onPointerDown={closeSheet} />
                <ShopEditSheet
                  selection={selection}
                  href={shopPublic}
                  busy={editing}
                  locked={building || busy}
                  reply={sheetReply}
                  error={sheetError}
                  onRun={async (text, opts) => (await runEdit(text, opts)).ok}
                  onImage={replaceImage}
                  onClose={closeSheet}
                />
              </>
            ) : null}
          </div>
          {mobilePreview ? (
            <ShopActionBar
              pending={pending}
              undoDepth={Number(shop?.undoDepth || 0)}
              working={working}
              building={building}
              failed={build?.status === "failed"}
              onBuild={() => void runBuild(true, true)}
              onUndo={() => void undo()}
            />
          ) : null}
        </div>
        {live && shopPublic && !isMobile ? (
          <aside
            aria-label="ویرایش فروشگاه"
            className="relative flex max-h-[50%] shrink-0 flex-col overflow-y-auto border-t border-line bg-paper px-3 pb-2 pt-2 lg:max-h-none lg:w-[22rem] lg:border-s lg:border-t-0 lg:px-4 lg:pt-3"
          >
            <ShopEditor
              brand={shop?.brand || ""}
              hidePrices={Boolean(shop?.hidePrices)}
              pending={pending}
              busy={editing}
              buildBusy={busy || building}
              selection={selection}
              messages={messages}
              onRun={async (text, opts) => (await runEdit(text, opts)).ok}
              onPublish={() => void runBuild(true, true)}
              onClearSelection={clearSelection}
            />
          </aside>
        ) : null}
      </div>
    </AppShell>
  );
}
