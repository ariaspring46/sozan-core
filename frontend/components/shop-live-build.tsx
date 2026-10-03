"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Copy, ExternalLink, Monitor, RefreshCw, Smartphone, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { shopHostLabel } from "@/components/domain-menu";
import { BuildProgress, type ProgressStep } from "@/components/build-progress";
import type { ShopSelection } from "@/components/shop-editor";

export type BuildStep = ProgressStep;

export type BuildLive = {
  status?: string;
  step?: string;
  stepLabel?: string;
  url?: string;
  urlOk?: boolean;
  error?: string;
  errorClass?: string;
  jobId?: string;
  releaseId?: string;
  runAttempt?: number;
  startedAt?: string;
  elapsedSec?: number | null;
  pipeline?: BuildStep[];
};

export type PreviewPatch = {
  find?: string;
  replace?: string;
  colors?: Record<string, string>;
  reload?: boolean;
  reset?: boolean;
  undo?: boolean;
  /** با `undo`: تعداد ویرایش‌هایی که هنوز باقی است؛ پیش‌نمایش بقیه را دوباره می‌چیند. */
  to?: number;
  /** شمارهٔ ویرایش در پشتهٔ «برگشت»؛ beacon با آن می‌داند کدام تکه را بردارد. */
  seq?: number;
  viewPath?: string;
};

const OPEN_KEY = "sozan-preview-open";
const HOLD_HINT_KEY = "sozan-shop-hold-hint";
const PAGES = [
  { path: "/", label: "خانه" },
  { path: "/products", label: "کالاها" },
  { path: "/cart", label: "سبد" },
] as const;

function elapsedFrom(startedAt?: string, elapsedSec?: number | null, live?: boolean) {
  if (!live && typeof elapsedSec === "number") return elapsedSec;
  if (!startedAt) return typeof elapsedSec === "number" ? elapsedSec : 0;
  const t = Date.parse(startedAt);
  if (Number.isNaN(t)) return typeof elapsedSec === "number" ? elapsedSec : 0;
  return Math.max(0, Math.floor((Date.now() - t) / 1000));
}

function normalizeViewPath(raw: string) {
  try {
    const href = raw.startsWith("http") ? raw : `https://preview.invalid${raw.startsWith("/") ? raw : `/${raw}`}`;
    const url = new URL(href);
    url.searchParams.delete("sozan");
    const query = url.searchParams.toString();
    return `${url.pathname}${query ? `?${query}` : ""}${url.hash}` || "/";
  } catch {
    return "/";
  }
}

function frameUrl(href: string, path: string, bust: number, mode: "design" | "browse") {
  const origin = href.replace(/\/$/, "");
  const clean = normalizeViewPath(path).split("?")[0].split("#")[0] || "/";
  return `${origin}${clean}?sozan=${mode}&t=${bust}`;
}

function previewOrigin(href: string): string {
  try {
    const url = new URL(href);
    if (url.protocol === "http:" || url.protocol === "https:") return url.origin;
  } catch {
    /* ignore */
  }
  return "";
}

function postToPreview(win: Window | null | undefined, href: string, data: object) {
  const origin = previewOrigin(href);
  if (!win || !origin) return;
  win.postMessage(data, origin);
}

function readOpen() {
  try {
    return localStorage.getItem(OPEN_KEY) !== "0";
  } catch {
    return true;
  }
}

function writeOpen(open: boolean) {
  try {
    localStorage.setItem(OPEN_KEY, open ? "1" : "0");
  } catch {
    /* ignore quota */
  }
}

function ShopLiveReady({ href }: { href: string }) {
  const host = href ? shopHostLabel(href) : "";
  const inner = (
    <>
      <div className="relative mx-auto h-16 w-16">
        <span className="absolute inset-0 rounded-full border border-accent/30" />
        <span className="absolute inset-4 rounded-full bg-accent/25" />
      </div>
      <p className="text-xs text-warm">آنلاین</p>
      <p className="mt-1 text-base font-bold">فروشگاه زنده است</p>
      {host ? (
        <p className="mt-1 truncate text-xs text-muted" dir="ltr">
          {host}
        </p>
      ) : (
        <p className="mt-1 text-xs text-muted">سایت در حال آماده شدن</p>
      )}
    </>
  );

  if (href) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="relative block overflow-hidden rounded-3xl border border-accent/25 bg-paper px-4 py-5 text-center shadow-card"
      >
        {inner}
        <span className="mt-3 inline-flex items-center gap-1 text-sm text-warm">
          باز کردن ویترین
          <ExternalLink size={14} />
        </span>
      </a>
    );
  }

  return (
    <section className="relative overflow-hidden rounded-3xl border border-accent/25 bg-paper px-4 py-5 text-center shadow-card">
      {inner}
    </section>
  );
}

function IconBtn({
  label,
  active,
  onClick,
  children,
  className,
}: {
  label: string;
  active?: boolean;
  onClick: () => void;
  children: ReactNode;
  className?: string;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={cn(
        "inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-warm sm:h-9 sm:w-9",
        active ? "bg-accent/15" : "hover:bg-canvas",
        className,
      )}
    >
      {children}
    </button>
  );
}

function ShopLivePreview({
  href,
  build,
  bust,
  overlay,
  seconds,
  pendingBuild = 0,
  buildBusy = false,
  applyPatch,
  onBuild,
  onRetry,
  onViewPath,
  onPick,
  seekPath,
  clearPick = 0,
  compact = false,
}: {
  href: string;
  build: BuildLive | null;
  bust: number;
  overlay: boolean;
  seconds: number;
  pendingBuild?: number;
  buildBusy?: boolean;
  applyPatch?: PreviewPatch | null;
  onBuild?: () => void;
  onRetry?: () => void;
  onViewPath?: (path: string) => void;
  onPick?: (selection: ShopSelection, longPress: boolean) => void;
  seekPath?: string;
  clearPick?: number;
  /** موبایل: فقط خود سایت (در اندازهٔ واقعی گوشی)، بدون نوار و تب؛ ویرایش با نگه داشتن انگشت. */
  compact?: boolean;
}) {
  const host = shopHostLabel(href);
  const [path, setPath] = useState("/");
  const [open, setOpen] = useState(true);
  const [phone, setPhone] = useState(false);
  const [designMode, setMode] = useState<"design" | "browse">("design");
  const mode = compact ? "browse" : designMode;
  const [reload, setReload] = useState(0);
  const [pick, setPick] = useState("");
  const [frameLoaded, setFrameLoaded] = useState(false);
  const [frameStale, setFrameStale] = useState(false);
  const [frameDead, setFrameDead] = useState(false);
  const [holdHint, setHoldHint] = useState(false);
  const undoTimer = useRef(0);
  const frameRef = useRef<HTMLIFrameElement>(null);
  const src = useMemo(() => frameUrl(href, path, bust + reload, mode), [href, path, bust, reload, mode]);

  useEffect(() => {
    setFrameLoaded(false);
    setFrameStale(false);
    const timer = window.setTimeout(() => setFrameStale(true), 8000);
    return () => window.clearTimeout(timer);
  }, [src]);
  // یک iframe که صفحهٔ خطای مرورگر یا پراکسی را بار کند «load» می‌دهد؛ پس خودِ نشانی را بی‌صدا می‌سنجیم.
  useEffect(() => {
    setFrameDead(false);
    const controller = new AbortController();
    let timedOut = false;
    const timer = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, 10000);
    fetch(src, { method: "HEAD", mode: "no-cors", cache: "no-store", signal: controller.signal })
      .catch(() => {
        if (!controller.signal.aborted || timedOut) setFrameDead(true);
      })
      .finally(() => window.clearTimeout(timer));
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [src]);
  const pipeline = build?.pipeline || [];
  const live = overlay && (build?.status === "running" || build?.status === "queued");
  const failed = overlay && build?.status === "failed";
  const title = live ? build?.stepLabel || "در حال اعمال تغییر…" : build?.error || "ساخت کامل نشد";

  useEffect(() => {
    setOpen(readOpen());
  }, []);

  // یک بار برای هر گوشی: می‌گوید ویرایش با نگه داشتن انگشت است؛ بعد از اولین نگه داشتن یا چند ثانیه محو می‌شود.
  useEffect(() => {
    if (!compact) return;
    try {
      if (localStorage.getItem(HOLD_HINT_KEY)) return;
    } catch {
      /* ignore */
    }
    setHoldHint(true);
    const timer = window.setTimeout(() => dismissHint(), 9000);
    return () => window.clearTimeout(timer);
  }, [compact]);

  function dismissHint() {
    setHoldHint(false);
    try {
      localStorage.setItem(HOLD_HINT_KEY, "1");
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    if (overlay) setOpen(true);
  }, [overlay]);

  function setPreviewOpen(next: boolean) {
    setOpen(next);
    writeOpen(next);
  }

  function go(next: string) {
    setPath(next);
    onViewPath?.(next);
    setReload((value) => value + 1);
  }

  useEffect(() => {
    const onMsg = (event: MessageEvent) => {
      const data = event.data;
      if (!data || data.source !== "sozan-preview") return;
      try {
        if (new URL(event.origin).host !== new URL(href).host) return;
      } catch {
        return;
      }
      if (data.undone) {
        window.clearTimeout(undoTimer.current);
        setReload((value) => value + 1);
        return;
      }
      const next = normalizeViewPath(String(data.path || "/"));
      setPath(next);
      onViewPath?.(next);
      const raw = data.pick && typeof data.pick === "object" ? data.pick : null;
      const picked = raw && typeof raw.text === "string" ? raw.text.trim() : "";
      const tag = raw && typeof raw.tag === "string" ? raw.tag : "";
      const src = raw && typeof raw.src === "string" ? raw.src : "";
      const kind = raw && (raw.kind === "image" || raw.kind === "text" || raw.kind === "block") ? raw.kind : undefined;
      if (picked || tag || src) {
        const label = picked ? (tag ? `${tag} · ${picked}` : picked) : tag;
        setPick(label);
        if (data.longPress) dismissHint();
        const behind = raw && raw.image && typeof raw.image.src === "string" ? raw.image : null;
        onPick?.(
          {
            text: picked || (src ? "" : tag),
            tag,
            kind,
            src: src || undefined,
            alt: raw && typeof raw.alt === "string" ? raw.alt : undefined,
            image: behind ? { src: String(behind.src), alt: typeof behind.alt === "string" ? behind.alt : undefined } : undefined,
            product: raw && typeof raw.product === "string" && raw.product ? raw.product : undefined,
          },
          Boolean(data.longPress),
        );
      }
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [href, onViewPath, onPick]);

  useEffect(() => {
    if (!clearPick) return;
    setPick("");
    postToPreview(frameRef.current?.contentWindow, href, { source: "sozan-panel", type: "clear" });
  }, [clearPick, href]);

  useEffect(() => {
    if (!seekPath || seekPath === "/" || pendingBuild > 0) return;
    if (build?.status !== "ready") return;
    if (path === seekPath) return;
    go(seekPath);
  }, [seekPath, build?.status, pendingBuild]);

  useEffect(() => {
    if (!applyPatch) return;
    const win = frameRef.current?.contentWindow;
    if (applyPatch.undo) {
      postToPreview(win, href, { source: "sozan-panel", type: "undo", to: Number(applyPatch.to || 0) });
      // beacon بعد از برداشتن تکه‌ها خبر می‌دهد و پیش‌نمایش تازه می‌شود؛ اگر خبری نیامد، خودمان تازه می‌کنیم.
      window.clearTimeout(undoTimer.current);
      undoTimer.current = window.setTimeout(() => setReload((value) => value + 1), 1500);
      return;
    }
    if (applyPatch.reset) {
      postToPreview(win, href, { source: "sozan-panel", type: "reset" });
      setReload((value) => value + 1);
      return;
    }
    if (applyPatch.reload) {
      setReload((value) => value + 1);
      return;
    }
    postToPreview(win, href, { source: "sozan-panel", type: "apply", patch: applyPatch });
  }, [applyPatch, href]);

  const bar = (
    <div className="flex items-center gap-1 border-b border-line/70 px-2 py-1">
      <p className="min-w-0 flex-1 truncate px-1 text-xs text-warm" dir="ltr">
        <span className="hidden sm:inline">{host}</span>
        {path}
      </p>
      {open ? (
        <>
          <button
            type="button"
            onClick={() => setMode((value) => (value === "design" ? "browse" : "design"))}
            className={cn(
              "inline-flex min-h-11 shrink-0 items-center rounded-lg px-3 text-sm sm:min-h-9",
              mode === "design" ? "bg-accent/15 text-warm" : "text-muted hover:bg-canvas",
            )}
          >
            {mode === "design" ? "طراحی" : "مرور"}
          </button>
          {onBuild ? (
            <button
              type="button"
              onClick={() => onBuild()}
              disabled={buildBusy || (overlay && !failed) || (pendingBuild < 1 && !failed)}
              className={cn(
                "inline-flex min-h-11 shrink-0 items-center whitespace-nowrap rounded-lg px-3 text-sm sm:min-h-9",
                (pendingBuild > 0 || failed) && !(overlay && !failed) ? "bg-accentStrong text-onAccent" : "text-muted",
              )}
            >
              {failed ? "ساخت دوباره" : (
                <>
                  <span>بیلد</span>
                </>
              )}
              {pendingBuild > 0 ? ` (${pendingBuild.toLocaleString("fa-IR")})` : ""}
            </button>
          ) : null}
          <IconBtn label={phone ? "نمایش دسکتاپ" : "نمایش موبایل"} active={phone} onClick={() => setPhone((value) => !value)} className="hidden sm:inline-flex">
            {phone ? <Smartphone size={14} /> : <Monitor size={14} />}
          </IconBtn>
          <IconBtn label="تازه‌کردن" onClick={() => setReload((value) => value + 1)}>
            <RefreshCw size={14} />
          </IconBtn>
          <IconBtn
            className="hidden sm:inline-flex"
            label="کپی نشانی عمومی"
            onClick={() => {
              void navigator.clipboard?.writeText(href.replace(/\/$/, "") + (path.split("?")[0] || "/"));
            }}
          >
            <Copy size={14} />
          </IconBtn>
          <a
            href={href.replace(/\/$/, "") + (path.split("?")[0] || "/")}
            target="_blank"
            rel="noreferrer"
            aria-label="باز کردن ویترین در تب جدید"
            title="باز کردن ویترین در تب جدید"
            className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-warm hover:bg-canvas sm:h-9 sm:w-9"
          >
            <ExternalLink size={16} />
          </a>
          <IconBtn label="بستن پیش‌نمایش" onClick={() => setPreviewOpen(false)}>
            <X size={14} />
          </IconBtn>
        </>
      ) : (
        <button
          type="button"
          onClick={() => setPreviewOpen(true)}
          className="inline-flex min-h-11 shrink-0 items-center rounded-lg px-3 text-sm text-warm hover:bg-canvas"
        >
          باز کردن
        </button>
      )}
    </div>
  );

  if (!compact && !open) {
    return <section className="shrink-0 overflow-hidden rounded-2xl border border-accent/25 bg-paper shadow-card">{bar}</section>;
  }

  return (
    <section
      className={cn(
        "relative flex flex-1 flex-col overflow-hidden bg-paper",
        compact ? "min-h-0" : "min-h-[10rem] rounded-2xl border border-accent/25 shadow-card sm:min-h-[14rem]",
      )}
    >
      {compact ? null : bar}
      {compact ? null : (
        <div className="flex shrink-0 gap-1 border-b border-line/60 px-2 py-1">
          {PAGES.map((page) => (
            <button
              key={page.path}
              type="button"
              onClick={() => go(page.path)}
              className={cn(
                "tap rounded-lg px-3 py-2 text-[13px]",
                (page.path === "/" ? path === "/" : path.startsWith(page.path)) ? "bg-accent/15 text-warm" : "text-muted hover:bg-canvas",
              )}
            >
              {page.label}
            </button>
          ))}
          {pick ? (
            <span className="ms-auto max-w-[45%] truncate rounded-lg bg-accent/10 px-2 py-1 text-xs text-warm">
              {pick}
            </span>
          ) : (
            <span className="ms-auto px-2 py-1 text-xs text-muted">
              {mode === "design" ? "روی هر بخش سایت بزن" : "در حال مرور"}
            </span>
          )}
        </div>
      )}
      <div className="relative min-h-0 w-full flex-1 overflow-hidden bg-canvas">
        <div
          className={cn("absolute", compact ? "inset-0" : phone ? "origin-top" : "origin-top-right")}
          style={
            compact
              ? undefined
              : {
                  width: "133.333%",
                  height: "133.333%",
                  transform: "scale(0.75)",
                  top: 0,
                  ...(phone ? { left: "-16.666%" } : { right: 0 }),
                }
          }
        >
          <iframe
            ref={frameRef}
            key={`${mode}:${bust}:${reload}`}
            title="پیش‌نمایش فروشگاه"
            src={src}
            width="100%"
            height="100%"
            className={cn("h-full border-0 bg-white", phone && !compact ? "mx-auto w-full max-w-[430px]" : "w-full min-w-full")}
            onLoad={() => {
              setFrameLoaded(true);
              setFrameStale(false);
              if (!applyPatch || applyPatch.reload || applyPatch.reset || applyPatch.undo) return;
              postToPreview(frameRef.current?.contentWindow, href, {
                source: "sozan-panel",
                type: "apply",
                patch: applyPatch,
              });
            }}
          />
        </div>
        {compact && holdHint && !overlay ? (
          <p
            role="status"
            className="pointer-events-none absolute inset-x-3 bottom-3 z-10 rounded-2xl border border-accent/30 bg-paper/95 px-3 py-2 text-center text-sm leading-6 text-warm shadow-card"
          >
            هر جای سایت را بخواهی ویرایش کنی، انگشتت را رویش نگه دار.
          </p>
        ) : null}
        {pendingBuild > 0 && !overlay && !compact ? (
          <button
            type="button"
            onClick={() => setReload((value) => value + 1)}
            className="absolute bottom-3 left-1/2 inline-flex min-h-11 -translate-x-1/2 items-center whitespace-nowrap rounded-full border border-accent/30 bg-paper/95 px-4 text-sm text-warm shadow-card"
          >
            پیش‌نمایش را تازه کن
          </button>
        ) : null}
        {((frameStale && !frameLoaded) || frameDead) && !overlay ? (
          <div className="absolute inset-x-3 top-3 rounded-2xl border border-danger/30 bg-paper/95 px-3 py-2 shadow-card">
            <p className="text-sm text-danger">پیش‌نمایش بار نشد — تازه کن</p>
            <button type="button" className="inline-flex min-h-11 items-center text-sm text-warm underline" onClick={() => setReload((value) => value + 1)}>
              تازه کن
            </button>
          </div>
        ) : null}
        {overlay ? <BuildProgress cover steps={pipeline} title={title} seconds={seconds} live={live} failed={failed} onRetry={onRetry} /> : null}
      </div>
    </section>
  );
}

function ShopPipeline({
  build,
  live,
  failed,
  seconds,
  onRetry,
}: {
  build: BuildLive;
  live: boolean;
  failed: boolean;
  seconds: number;
  onRetry?: () => void;
}) {
  const title = live ? build.stepLabel || "سوزان در حال ساخت سایت است…" : build.error || "ساخت کامل نشد";
  return <BuildProgress steps={build.pipeline || []} title={title} seconds={seconds} live={live} failed={failed} onRetry={onRetry} />;
}

export function ShopLiveBuild({
  build,
  href = "",
  previewKey = 0,
  pendingBuild = 0,
  buildBusy = false,
  applyPatch,
  onBuild,
  onRetry,
  onViewPath,
  onPick,
  seekPath,
  clearPick = 0,
  compact = false,
}: {
  build: BuildLive | null;
  href?: string;
  previewKey?: number;
  pendingBuild?: number;
  buildBusy?: boolean;
  applyPatch?: PreviewPatch | null;
  onBuild?: () => void;
  onRetry?: () => void;
  onViewPath?: (path: string) => void;
  onPick?: (selection: ShopSelection, longPress: boolean) => void;
  seekPath?: string;
  clearPick?: number;
  compact?: boolean;
}) {
  const status = build?.status || "";
  const live = status === "running" || status === "queued";
  const failed = status === "failed";
  const ready = status === "ready";
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    const read = () => setSeconds(elapsedFrom(build?.startedAt, build?.elapsedSec, live));
    read();
    if (!live) return;
    const timer = window.setInterval(read, 1000);
    return () => window.clearInterval(timer);
  }, [live, build?.startedAt, build?.elapsedSec]);

  if (!build || (!live && !failed && !ready && !href)) return null;
  if (href) {
    return (
      <ShopLivePreview
        href={href}
        build={build}
        bust={previewKey}
        overlay={live || failed}
        seconds={seconds}
        pendingBuild={pendingBuild}
        buildBusy={buildBusy}
        applyPatch={applyPatch}
        onBuild={onBuild}
        onRetry={onRetry}
        onViewPath={onViewPath}
        onPick={onPick}
        seekPath={seekPath}
        clearPick={clearPick}
        compact={compact}
      />
    );
  }
  if (ready) return <ShopLiveReady href="" />;
  return <ShopPipeline build={build} live={live} failed={failed} seconds={seconds} onRetry={onRetry} />;
}
