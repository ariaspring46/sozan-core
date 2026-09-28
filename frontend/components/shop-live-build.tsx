"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Copy, ExternalLink, Monitor, RefreshCw, Smartphone, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { shopHostLabel } from "@/components/domain-menu";

export type BuildStep = { id: string; label: string; state: "done" | "active" | "wait" | "fail" };

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
  viewPath?: string;
};

const OPEN_KEY = "sozan-preview-open";
const PAGES = [
  { path: "/", label: "خانه" },
  { path: "/products", label: "کالاها" },
  { path: "/cart", label: "سبد" },
] as const;

function clock(sec: number) {
  const m = Math.floor(sec / 60).toLocaleString("fa-IR");
  const s = (sec % 60).toLocaleString("fa-IR").padStart(2, "۰");
  return `${m}:${s}`;
}

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
      <p className="text-[11px] tracking-[0.22em] text-warm">آنلاین</p>
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
}: {
  label: string;
  active?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={cn(
        "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-warm",
        active ? "bg-accent/15" : "hover:bg-canvas",
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
  onViewTarget,
  seekPath,
  clearPick = 0,
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
  onViewTarget?: (text: string, tag?: string) => void;
  seekPath?: string;
  clearPick?: number;
}) {
  const host = shopHostLabel(href);
  const [path, setPath] = useState("/");
  const [open, setOpen] = useState(true);
  const [phone, setPhone] = useState(false);
  const [mode, setMode] = useState<"design" | "browse">("design");
  const [reload, setReload] = useState(0);
  const [pick, setPick] = useState("");
  const [frameLoaded, setFrameLoaded] = useState(false);
  const [frameStale, setFrameStale] = useState(false);
  const frameRef = useRef<HTMLIFrameElement>(null);
  const src = useMemo(() => frameUrl(href, path, bust + reload, mode), [href, path, bust, reload, mode]);

  useEffect(() => {
    setFrameLoaded(false);
    setFrameStale(false);
    const timer = window.setTimeout(() => setFrameStale(true), 8000);
    return () => window.clearTimeout(timer);
  }, [src]);
  const pipeline = build?.pipeline || [];
  const live = overlay && (build?.status === "running" || build?.status === "queued");
  const failed = overlay && build?.status === "failed";
  const title = live ? build?.stepLabel || "در حال اعمال تغییر…" : build?.error || "ساخت کامل نشد";

  useEffect(() => {
    setOpen(readOpen());
  }, []);

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
      const next = normalizeViewPath(String(data.path || "/"));
      setPath(next);
      onViewPath?.(next);
      const picked = data.pick && typeof data.pick.text === "string" ? data.pick.text.trim() : "";
      const tag = data.pick && typeof data.pick.tag === "string" ? data.pick.tag : "";
      if (picked || tag) {
        const label = picked ? (tag ? `${tag} · ${picked}` : picked) : tag;
        setPick(label);
        onViewTarget?.(picked || tag, tag);
      }
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [href, onViewPath, onViewTarget]);

  useEffect(() => {
    if (clearPick) setPick("");
  }, [clearPick]);

  useEffect(() => {
    if (!seekPath || seekPath === "/" || pendingBuild > 0) return;
    if (build?.status !== "ready") return;
    if (path === seekPath) return;
    go(seekPath);
  }, [seekPath, build?.status, pendingBuild]);

  useEffect(() => {
    if (!applyPatch) return;
    const win = frameRef.current?.contentWindow;
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
    <div className="flex items-center gap-1 border-b border-line/70 px-2 py-1.5">
      <p className="min-w-0 flex-1 truncate px-1 text-[11px] tracking-[0.14em] text-warm" dir="ltr">
        {host}
        {path}
      </p>
      {open ? (
        <>
          <button
            type="button"
            onClick={() => setMode((value) => (value === "design" ? "browse" : "design"))}
            className={cn(
              "shrink-0 rounded-lg px-2 py-1 text-xs",
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
                "shrink-0 whitespace-nowrap rounded-lg px-2 py-1 text-xs",
                (pendingBuild > 0 || failed) && !(overlay && !failed) ? "bg-accent text-onAccent" : "text-muted",
              )}
            >
              {failed ? "ساخت دوباره" : "انتشار تغییرات"}
              {pendingBuild > 0 ? ` (${pendingBuild.toLocaleString("fa-IR")})` : ""}
            </button>
          ) : null}
          <IconBtn label={phone ? "نمایش دسکتاپ" : "نمایش موبایل"} active={phone} onClick={() => setPhone((value) => !value)}>
            {phone ? <Smartphone size={14} /> : <Monitor size={14} />}
          </IconBtn>
          <IconBtn label="تازه‌کردن" onClick={() => setReload((value) => value + 1)}>
            <RefreshCw size={14} />
          </IconBtn>
          <IconBtn
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
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-warm hover:bg-canvas"
          >
            <ExternalLink size={14} />
          </a>
          <IconBtn label="بستن پیش‌نمایش" onClick={() => setPreviewOpen(false)}>
            <X size={14} />
          </IconBtn>
        </>
      ) : (
        <button
          type="button"
          onClick={() => setPreviewOpen(true)}
          className="shrink-0 rounded-lg px-2 py-1 text-xs text-warm hover:bg-canvas"
        >
          باز کردن
        </button>
      )}
    </div>
  );

  if (!open) {
    return <section className="shrink-0 overflow-hidden rounded-2xl border border-accent/25 bg-paper shadow-card">{bar}</section>;
  }

  return (
    <section className="relative flex min-h-[10rem] flex-1 flex-col sm:min-h-[14rem] overflow-hidden rounded-2xl border border-accent/25 bg-paper shadow-card">
      {bar}
      <div className="flex shrink-0 gap-1 border-b border-line/60 px-2 py-1">
        {PAGES.map((page) => (
          <button
            key={page.path}
            type="button"
            onClick={() => go(page.path)}
            className={cn(
              "rounded-lg px-2 py-1 text-xs",
              (page.path === "/" ? path === "/" : path.startsWith(page.path)) ? "bg-accent/15 text-warm" : "text-muted hover:bg-canvas",
            )}
          >
            {page.label}
          </button>
        ))}
        {pick ? (
          <span className="ms-auto max-w-[45%] truncate rounded-lg bg-accent/10 px-2 py-1 text-[11px] text-warm">
            {pick}
          </span>
        ) : (
          <span className="ms-auto px-2 py-1 text-[11px] text-muted">
            {mode === "design" ? "روی المان بزن" : "در حال مرور"}
          </span>
        )}
      </div>
      <div className="relative min-h-0 w-full flex-1 overflow-hidden bg-canvas">
        <div
          className={cn("absolute", phone ? "origin-top" : "origin-top-right")}
          style={{
            width: "133.333%",
            height: "133.333%",
            transform: "scale(0.75)",
            top: 0,
            ...(phone ? { left: "-16.666%" } : { right: 0 }),
          }}
        >
          <iframe
            ref={frameRef}
            key={`${mode}:${bust}:${reload}`}
            title="پیش‌نمایش فروشگاه"
            src={src}
            width="100%"
            height="100%"
            className={cn("h-full border-0 bg-white", phone ? "mx-auto w-full max-w-[430px]" : "w-full min-w-full")}
            onLoad={() => {
              setFrameLoaded(true);
              setFrameStale(false);
              if (!applyPatch || applyPatch.reload || applyPatch.reset) return;
              postToPreview(frameRef.current?.contentWindow, href, {
                source: "sozan-panel",
                type: "apply",
                patch: applyPatch,
              });
            }}
          />
        </div>
        {pendingBuild > 0 && !overlay ? (
          <button
            type="button"
            onClick={() => setReload((value) => value + 1)}
            className="absolute inset-x-3 top-3 rounded-2xl border border-accent/30 bg-paper/95 px-3 py-2 text-sm text-warm shadow-card"
          >
            پیش‌نمایش را تازه کن
          </button>
        ) : null}
        {frameStale && !frameLoaded && !overlay ? (
          <div className="absolute inset-x-3 top-3 rounded-2xl border border-danger/30 bg-paper/95 px-3 py-2 shadow-card">
            <p className="text-sm text-danger">پیش‌نمایش بار نشد — تازه کن</p>
            <button type="button" className="mt-1 text-sm text-warm underline" onClick={() => setReload((value) => value + 1)}>
              تازه کن
            </button>
          </div>
        ) : null}
        {overlay ? (
          <div className="absolute inset-x-3 bottom-3 rounded-2xl border border-accent/25 bg-paper/95 px-3 py-2 shadow-card">
            <p className="text-[11px] tracking-[0.18em] text-warm">{live ? "در حال ساخت فروشگاه…" : "آخرین ساخت"}</p>
            <p className={cn("mt-0.5 text-sm", failed ? "text-danger" : "text-ink")}>{title}</p>
            <p className={cn("text-xs", failed ? "text-danger" : "text-muted")}>
              {live ? `زمان ساخت ${clock(seconds)}` : failed ? "ساخت کامل نشد." : ""}
            </p>
            {failed && onRetry ? (
              <button type="button" className="mt-2 text-sm text-warm underline" onClick={onRetry}>
                دوباره بساز
              </button>
            ) : null}
            {pipeline.length ? (
              <ol className="mt-2 space-y-1">
                {pipeline.map((step) => (
                  <li key={step.id} className="flex items-center gap-2 text-xs">
                    <span
                      className={cn(
                        "h-1.5 w-1.5 shrink-0 rounded-full",
                        step.state === "done" && "bg-accent",
                        step.state === "active" && "sozan-breathe bg-signal",
                        step.state === "fail" && "bg-danger",
                        step.state === "wait" && "border border-line",
                      )}
                    />
                    <span className={cn(step.state === "wait" && "text-muted", step.state === "fail" && "text-danger")}>
                      {step.label}
                    </span>
                  </li>
                ))}
              </ol>
            ) : null}
          </div>
        ) : null}
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
  const pipeline = build.pipeline || [];
  const title = live ? build.stepLabel || "کارخانه در حال ساخت سایت است…" : "ساخت کامل نشد";
  return (
    <section
      className={cn(
        "relative overflow-hidden rounded-3xl border bg-paper px-4 py-4 shadow-card",
        live ? "border-accent/30" : "border-danger/40",
      )}
    >
      <div className="relative flex items-center gap-4">
        <div className="relative h-14 w-14 shrink-0">
          <span className={cn("absolute inset-1 rounded-full", live ? "sozan-glow bg-accent/15" : "bg-danger/10")} />
          <span
            className={cn(
              "absolute left-1/2 top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full",
              live ? "sozan-breathe bg-signal" : "bg-danger",
            )}
          />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] tracking-[0.22em] text-warm">{live ? "در حال ساخت فروشگاه…" : "آخرین ساخت"}</p>
          <p className="mt-1 text-sm font-medium leading-6 text-ink">{title}</p>
          <p className={cn("mt-0.5 text-xs", failed ? "text-danger" : "text-muted")}>
            {live ? `زمان ساخت ${clock(seconds)}` : "ساخت کامل نشد."}
          </p>
          {failed && onRetry ? (
            <button type="button" className="mt-2 text-sm text-warm underline" onClick={onRetry}>
              دوباره بساز
            </button>
          ) : null}
        </div>
      </div>
      {pipeline.length ? (
        <ol className="relative mt-4 space-y-2">
          {pipeline.map((step) => (
            <li key={step.id} className="flex items-center gap-3 text-sm">
              <span
                className={cn(
                  "flex h-2.5 w-2.5 shrink-0 items-center justify-center rounded-full",
                  step.state === "done" && "bg-accent",
                  step.state === "active" && "sozan-breathe bg-signal",
                  step.state === "fail" && "bg-danger outline outline-2 outline-danger/30",
                  step.state === "wait" && "border border-line bg-transparent",
                )}
              />
              <span
                className={cn(
                  "leading-6",
                  step.state === "wait" && "text-muted",
                  step.state === "fail" && "text-danger",
                  step.state === "active" && "text-warm",
                )}
              >
                {step.label}
              </span>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
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
  onViewTarget,
  seekPath,
  clearPick = 0,
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
  onViewTarget?: (text: string, tag?: string) => void;
  seekPath?: string;
  clearPick?: number;
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
        onViewTarget={onViewTarget}
        seekPath={seekPath}
        clearPick={clearPick}
      />
    );
  }
  if (ready) return <ShopLiveReady href="" />;
  return <ShopPipeline build={build} live={live} failed={failed} seconds={seconds} onRetry={onRetry} />;
}
