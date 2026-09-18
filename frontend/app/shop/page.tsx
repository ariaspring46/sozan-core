"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { ChatThread, type ChatMsg } from "@/components/chat-thread";
import { DomainMenu, shopPublicUrl, type ShopState } from "@/components/domain-menu";
import { ShopLiveBuild, type BuildLive, type PreviewPatch } from "@/components/shop-live-build";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

type ScanState = {
  status?: string;
  productCount?: number;
  error?: string;
  handles?: string[];
  needsReview?: boolean;
  imported?: number;
  noImage?: number;
  noPrice?: number;
  rejected?: number;
};
type TurnOutcome = {
  route?: string;
  actions?: string[];
  verified?: boolean;
  rolledBack?: boolean;
  needsRebuild?: boolean;
  state?: string;
};
type ShopPayload = { shop: ShopState; messages: ChatMsg[]; scan?: ScanState; build?: BuildLive; turn?: TurnOutcome; patched?: boolean };

export default function ShopPage() {
  const [shop, setShop] = useState<ShopState | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [scan, setScan] = useState<ScanState | null>(null);
  const [build, setBuild] = useState<BuildLive | null>(null);
  const [turn, setTurn] = useState<TurnOutcome | null>(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const [viewPath, setViewPath] = useState("/");
  const [viewTarget, setViewTarget] = useState("");
  const [previewKey, setPreviewKey] = useState(0);
  const [applyPatch, setApplyPatch] = useState<PreviewPatch | null>(null);
  const [seekPath, setSeekPath] = useState("");
  const prevStatus = useRef("");
  const chatKey = useRef("");
  const buildKey = useRef("");

  const apply = (data: ShopPayload) => {
    setShop(data.shop);
    setMessages(data.messages || []);
    if (data.scan) setScan(data.scan);
    if (data.build) setBuild(data.build);
    if (data.turn) setTurn(data.turn);
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
      : scan?.needsReview && importedCount
        ? `${importedCount} کالا وارد شد؛ عکس کم است، بعداً عکس بگذار.`
        : scan?.needsReview
          ? `اسکن مشکوک است؛ ${importedCount} کالا در صف بازبینی است.`
        : scan?.status === "done" && importedCount
          ? `${importedCount} کالا وارد شد` +
            (scan.rejected ? `، ${scan.rejected} رد` : "") +
            (scan.noImage ? `، ${scan.noImage} بدون عکس` : "") +
            (scan.noPrice ? `، ${scan.noPrice} بدون قیمت` : "") +
            "."
          : scan?.status === "error"
            ? scan.error || "اسکن کانال کامل نشد."
            : "";
  const turnNote = turn
    ? `فهمیدم: ${turn.route || "—"}. اکشن‌ها: ${(turn.actions || []).join("، ") || "—"}. ${
        turn.rolledBack ? "برگشت داده شد." : turn.verified ? "verify شد." : ""
      } ${turn.needsRebuild ? "نیاز به بیلد دارد." : "روی سایت زنده است."}`
    : "";
  const live = Boolean(
    shop && (shop.status === "ready" || (shop.slug && (shop.url || shop.publicHost || shop.port))),
  );
  const chatting = live || Boolean(shop && shop.status !== "idle");
  const thread = messages.filter((msg) => msg.kind !== "build");

  const runBuild = useCallback(async (rebuild?: boolean, reviseOnly?: boolean) => {
    setBusy(true);
    setError("");
    try {
      const key = buildKey.current || crypto.randomUUID();
      buildKey.current = key;
      const data = await api<ShopPayload & { result?: { error?: string } }>("/shop/build", {
        method: "POST",
        headers: { "Idempotency-Key": key },
        body: JSON.stringify({
          prompt: reviseOnly ? shop?.brand || "" : rebuild ? "از نو بساز" : shop?.brand || "",
          rebuild: Boolean(rebuild),
          reviseOnly: Boolean(reviseOnly),
        }),
      });
      apply(data);
      setApplyPatch(null);
      buildKey.current = "";
      if (data.result?.error) setError(data.result.error);
    } catch (err) {
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
      <div className={cn("relative flex h-full flex-col", building ? "sozan-aurora" : "sozan-chat")}>
        {error ? <p className="relative px-4 pt-3 text-sm text-danger">{error}</p> : null}
        {turnNote ? <p className="relative px-4 pt-3 text-sm text-warm">{turnNote}</p> : null}
        {scanNote ? (
          <p className={`relative px-4 pt-3 text-sm ${scan?.status === "error" ? "text-danger" : "text-warm"}`}>
            {scanNote}
          </p>
        ) : null}
        <div className="relative min-h-0 flex-1">
          <ChatThread
            messages={thread}
            busy={busy}
            pendingText={pending}
            livePanel={
              <ShopLiveBuild
                build={build}
                href={shopPublicUrl(shop, build?.url)}
                previewKey={previewKey}
                pendingBuild={Number(shop?.pendingBuild || 0)}
                buildBusy={busy || building}
                applyPatch={applyPatch}
                seekPath={seekPath}
                onBuild={() => void runBuild(true, true)}
                onViewPath={setViewPath}
                onViewTarget={setViewTarget}
              />
            }
            placeholder={
              live
                ? viewTarget
                  ? `درباره «${viewTarget}» بگو چه عوض شود.`
                  : "روی همین صفحه بگو چه عوض شود. چند تغییر را در کادر ببین، بعد بیلد بزن."
                : chatting
                  ? "از فروشگاه بپرس، یا اگر آماده بودی بگو بساز."
                  : "اول حس فروشگاه را بگو، بعد رنگ، بعد ویژگی‌ها."
            }
            onSend={async (payload) => {
              setBusy(true);
              setPending(payload.text || payload.file?.name || "پیوست");
              setError("");
              try {
                const key = chatKey.current || crypto.randomUUID();
                chatKey.current = key;
                const body = new FormData();
                body.set("text", payload.text);
                body.set("viewPath", viewPath);
                if (viewTarget) body.set("viewTarget", viewTarget);
                if (payload.file) body.set("file", payload.file);
                const data = await api<ShopPayload & { patched?: boolean; preview?: PreviewPatch }>("/shop/chat", {
                  method: "POST",
                  headers: { "Idempotency-Key": key },
                  body,
                });
                apply(data);
                chatKey.current = "";
                if (data.patched) {
                  setApplyPatch(data.preview || {});
                  if (data.preview?.viewPath) setSeekPath(data.preview.viewPath);
                  if (data.preview?.reload || data.preview?.reset) setPreviewKey((value) => value + 1);
                }
              } catch (err) {
                setError(err instanceof Error ? err.message : "خطا");
              } finally {
                setPending("");
                setBusy(false);
              }
            }}
          />
        </div>
      </div>
    </AppShell>
  );
}
