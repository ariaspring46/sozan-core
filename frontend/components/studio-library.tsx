"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Copy, Download, Pencil, RefreshCw } from "lucide-react";
import { AuthMedia, MEDIA_RATIO, downloadMedia } from "@/components/auth-media";
import { EmptyState } from "@/components/empty-state";
import { api } from "@/lib/api";
import { formatWhen } from "@/lib/digits";
import { cn } from "@/lib/utils";

type AssetRow = { kind: string; channel: string; format: string; name: string; relPath: string };
type CopyRow = { channel: string; body: string };
type LibraryItem = {
  id: string;
  title: string;
  assets: AssetRow[];
  copies?: CopyRow[];
  compose?: string;
  composeStage?: string;
  startedAt?: number;
  at?: number;
};

const FORMAT_FA: Record<string, string> = {
  feed: "پست اینستاگرام",
  channel_post: "پست کانال",
  story: "استوری",
  wide: "عکس عریض",
  still: "عکس اصلی",
};
/** اول همان چیزی که فروشنده بیشتر می‌خواهد: مربع اینستاگرام، بعد پست کانال، استوری، عریض، عکس اصلی. */
const PRIMARY_ORDER = ["feed", "channel_post", "story", "wide", "still"];

function composeLabel(item: LibraryItem, now: number) {
  if (item.compose === "failed") return "ساخت کامل نشد";
  if (item.compose !== "running") return "";
  const started = Number(item.startedAt || 0);
  const elapsed = started > 0 ? Math.max(0, Math.round(now / 1000 - started)) : 0;
  const clock = elapsed ? ` · ${elapsed.toLocaleString("fa-IR")} ثانیه` : "";
  if (item.composeStage === "layout") return `چیدن متن${clock}`;
  return `ساخت عکس، حدود یک دقیقه${clock}`;
}

function isPicture(asset: AssetRow) {
  const name = asset.name.toLowerCase();
  return (
    asset.kind === "video" ||
    name.endsWith(".png") ||
    name.endsWith(".jpg") ||
    name.endsWith(".jpeg") ||
    name.endsWith(".webp") ||
    name.endsWith(".mp4")
  );
}

function mediaOf(item: LibraryItem) {
  return (item.assets || []).filter((asset) => asset.relPath && isPicture(asset));
}

function onShelf(item: LibraryItem) {
  return mediaOf(item).length > 0 || item.compose === "running" || item.compose === "failed";
}

function labelOf(asset: AssetRow) {
  if (asset.kind === "video") return asset.format === "reel" ? "ویدیوی ریلز" : "ویدیوی عریض";
  return FORMAT_FA[asset.format] || "تصویر";
}

function ratioOf(asset: AssetRow) {
  return MEDIA_RATIO[asset.format] || "1 / 1";
}

function pickPrimary(media: AssetRow[]) {
  const pictures = media.filter((asset) => asset.kind !== "video");
  for (const format of PRIMARY_ORDER) {
    const hit = pictures.find((asset) => asset.format === format);
    if (hit) return hit;
  }
  return pictures[0] || null;
}

function captionOf(item: LibraryItem) {
  const rows = item.copies || [];
  return (rows.find((row) => row.channel === "instagram") || rows[0])?.body?.trim() || "";
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const box = document.createElement("textarea");
    box.value = text;
    box.style.position = "fixed";
    box.style.opacity = "0";
    document.body.appendChild(box);
    box.select();
    document.execCommand("copy");
    box.remove();
  }
}

function fileName(item: LibraryItem, asset: AssetRow) {
  const ext = asset.name.includes(".") ? asset.name.split(".").pop() : asset.kind === "video" ? "mp4" : "png";
  return `${item.title.replace(/[\\/:*?"<>|\s]+/g, "-").slice(0, 40) || "sozan"}-${asset.format || "media"}.${ext}`;
}

function Action({ children, onClick, href }: { children: ReactNode; onClick?: () => void; href?: string }) {
  const cls = "inline-flex min-h-11 items-center gap-1.5 rounded-xl border border-line bg-canvas px-3 text-sm text-ink hover:border-accent/50";
  if (href) {
    return (
      <Link href={href} className={cls}>
        {children}
      </Link>
    );
  }
  return (
    <button type="button" className={cls} onClick={onClick}>
      {children}
    </button>
  );
}

function LibraryCard({ item, now, draft }: { item: LibraryItem; now: number; draft: boolean }) {
  const media = mediaOf(item);
  const status = composeLabel(item, now);
  const primary = pickPrimary(media);
  const others = media.filter((asset) => asset !== primary);
  const caption = captionOf(item);
  const [copied, setCopied] = useState(false);
  const [problem, setProblem] = useState("");

  async function save(asset: AssetRow) {
    setProblem("");
    try {
      await downloadMedia(item.id, asset.relPath, fileName(item, asset));
    } catch {
      setProblem("دانلود نشد. دوباره امتحان کن.");
    }
  }

  const meta = [formatWhen(item.at || 0), media.length ? `${media.length.toLocaleString("fa-IR")} خروجی` : ""].filter(Boolean).join(" · ");
  const tall = primary ? ratioOf(primary).startsWith("9") : false;

  return (
    <article className="space-y-3 rounded-2xl border border-line bg-paper p-4">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="wrap-any line-clamp-2 text-base font-bold leading-7">{item.title}</h2>
          {meta ? <p className="text-xs text-muted">{meta}</p> : null}
        </div>
        {status ? (
          <p className={cn("shrink-0 rounded-full bg-canvas px-2.5 py-1 text-xs", item.compose === "failed" ? "text-danger" : "text-warm")}>{status}</p>
        ) : null}
      </header>
      {item.compose === "failed" ? (
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-sm leading-7 text-muted">ساخت این مورد کامل نشد. در چت بگو «دوباره بساز».</p>
          <Action href="/chat">رفتن به چت</Action>
        </div>
      ) : null}
      {primary ? (
        <div className={cn(tall && "mx-auto w-full max-w-[18rem]")}>
          <AuthMedia campaignId={item.id} relPath={primary.relPath} kind={primary.kind} alt={item.title} ratio={ratioOf(primary)} eager={false} />
        </div>
      ) : null}
      {caption ? <p className="wrap-any line-clamp-3 whitespace-pre-wrap text-sm leading-7 text-muted">{caption}</p> : null}
      {problem ? (
        <p className="text-sm text-danger" role="alert">
          {problem}
        </p>
      ) : null}
      {primary || caption || !draft ? (
        <div className="flex flex-wrap gap-2">
          {caption ? (
            <Action
              onClick={() =>
                void copyText(caption).then(() => {
                  setCopied(true);
                  window.setTimeout(() => setCopied(false), 2000);
                })
              }
            >
              <Copy size={15} aria-hidden="true" />
              {copied ? "کپی شد" : "کپی کپشن"}
            </Action>
          ) : null}
          {primary ? (
            <Action onClick={() => void save(primary)}>
              <Download size={15} aria-hidden="true" />
              دانلود
            </Action>
          ) : null}
          {!draft ? (
            <Action href={`/campaigns/${item.id}`}>
              <Pencil size={15} aria-hidden="true" />
              ویرایش کمپین
            </Action>
          ) : null}
        </div>
      ) : null}
      {others.length ? (
        <details className="group">
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between text-sm text-warm">
            <span>همهٔ خروجی‌ها ({media.length.toLocaleString("fa-IR")})</span>
            <span aria-hidden="true" className="text-muted group-open:rotate-180">
              ▾
            </span>
          </summary>
          <ul className="mt-2 space-y-4">
            {others.map((asset) => (
              <li key={`${item.id}-${asset.relPath}`}>
                <div className="mb-1 flex items-center justify-between gap-2">
                  <p className="text-xs text-muted">{labelOf(asset)}</p>
                  <button type="button" className="tap inline-flex items-center gap-1 text-xs text-warm" onClick={() => void save(asset)}>
                    <Download size={13} aria-hidden="true" />
                    دانلود
                  </button>
                </div>
                <div className={cn(ratioOf(asset).startsWith("9") && "mx-auto w-full max-w-[18rem]")}>
                  <AuthMedia campaignId={item.id} relPath={asset.relPath} kind={asset.kind} alt={`${item.title} — ${labelOf(asset)}`} ratio={ratioOf(asset)} />
                </div>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </article>
  );
}

export function StudioLibrary() {
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [drafts, setDrafts] = useState<LibraryItem[]>([]);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (manual = false) => {
    if (manual) setRefreshing(true);
    try {
      const data = await api<{ items: LibraryItem[]; drafts: LibraryItem[] }>("/studio/content");
      setItems(data.items || []);
      setDrafts(data.drafts || []);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setReady(true);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const onVis = () => {
      if (document.visibilityState === "visible") void load();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [load]);

  const [now, setNow] = useState(() => Date.now());
  const shown = [
    ...items.filter(onShelf).map((item) => ({ item, draft: false })),
    ...drafts.filter(onShelf).map((item) => ({ item, draft: true })),
  ].sort((a, b) => (b.item.at || 0) - (a.item.at || 0));
  const live = shown.some(({ item }) => item.compose === "running");
  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [live]);

  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => void load(), 2000);
    return () => window.clearInterval(timer);
  }, [live, load]);

  const empty = ready && !shown.length;
  return (
    <div className="h-full space-y-3 overflow-y-auto px-4 py-3">
      {error ? (
        <div className="flex items-center justify-between gap-3 rounded-2xl border border-danger/40 bg-paper px-3 py-2">
          <p className="text-sm text-danger" role="alert">
            {error}
          </p>
          <button type="button" className="inline-flex min-h-11 shrink-0 items-center text-sm text-warm underline" onClick={() => void load(true)}>
            دوباره امتحان کن
          </button>
        </div>
      ) : null}
      {!ready && !error ? (
        <div className="space-y-3" aria-hidden="true">
          <div className="h-24 animate-pulse rounded-2xl bg-line/30" />
          <div className="h-64 animate-pulse rounded-2xl bg-line/20" />
        </div>
      ) : null}
      {ready && shown.length ? (
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted">{shown.length.toLocaleString("fa-IR")} مورد</p>
          <button
            type="button"
            aria-label="تازه‌کردن"
            className="inline-flex h-11 w-11 items-center justify-center rounded-lg text-warm hover:bg-canvas"
            onClick={() => void load(true)}
          >
            <RefreshCw size={16} className={cn(refreshing && "animate-spin")} aria-hidden="true" />
          </button>
        </div>
      ) : null}
      {empty && !error ? (
        <EmptyState
          title="هنوز رسانه‌ای ساخته نشده"
          detail="از چت بگو چه پست یا ویدیویی می‌خواهی. ساخته‌شده‌ها همین‌جا می‌مانند."
          action={
            <Link href="/chat" className="inline-flex min-h-11 items-center rounded-xl bg-accentStrong px-4 text-sm text-onAccent">
              رفتن به چت
            </Link>
          }
        />
      ) : null}
      {shown.map(({ item, draft }) => (
        <LibraryCard key={`${draft ? "d" : "i"}-${item.id}`} item={item} now={now} draft={draft} />
      ))}
    </div>
  );
}
