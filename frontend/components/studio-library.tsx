"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AuthMedia } from "@/components/auth-media";
import { EmptyState } from "@/components/empty-state";
import { api } from "@/lib/api";

type AssetRow = { kind: string; channel: string; format: string; name: string; relPath: string };
type LibraryItem = {
  id: string;
  title: string;
  assets: AssetRow[];
  compose?: string;
};

function composeLabel(status?: string) {
  if (status === "running") return "در حال ساخت";
  if (status === "failed") return "ساخت کامل نشد";
  return "";
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

function LibraryCard({ item }: { item: LibraryItem }) {
  const media = mediaOf(item);
  const status = composeLabel(item.compose);
  return (
    <article className="space-y-3 rounded-2xl border border-line bg-paper p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="truncate text-base font-bold">{item.title}</h2>
        {status ? <p className="shrink-0 text-xs text-warm">{status}</p> : null}
      </div>
      {media.length ? (
        <ul className="space-y-3">
          {media.map((asset) => (
            <li key={`${item.id}-${asset.relPath}`}>
              <AuthMedia campaignId={item.id} relPath={asset.relPath} kind={asset.kind} alt={item.title} />
            </li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}

export function StudioLibrary() {
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [drafts, setDrafts] = useState<LibraryItem[]>([]);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api<{ items: LibraryItem[]; drafts: LibraryItem[] }>("/studio/content");
      setItems(data.items || []);
      setDrafts(data.drafts || []);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setReady(true);
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

  const shown = [...items, ...drafts].filter(onShelf);
  const live = shown.some((item) => item.compose === "running");

  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => void load(), 2000);
    return () => window.clearInterval(timer);
  }, [live, load]);

  const empty = ready && !shown.length;
  return (
    <div className="h-full space-y-3 overflow-y-auto px-4 py-3">
      {error ? (
        <p className="text-sm text-danger" role="alert">
          {error}
        </p>
      ) : null}
      {!ready && !error ? <p className="text-sm text-muted">در حال خواندن…</p> : null}
      {empty && !error ? (
        <EmptyState
          title="هنوز رسانه‌ای ساخته نشده"
          detail="از چت بگو چه پست یا ویدیویی می‌خواهی. ساخته‌شده‌ها همین‌جا می‌مانند."
          action={
            <Link href="/chat" className="inline-flex min-h-11 items-center rounded-xl bg-accent px-4 text-sm text-onAccent">
              رفتن به چت
            </Link>
          }
        />
      ) : null}
      {shown.map((item) => (
        <LibraryCard key={item.id} item={item} />
      ))}
    </div>
  );
}
