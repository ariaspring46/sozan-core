"use client";

import { useEffect, useState } from "react";
import { AuthMedia } from "@/components/auth-media";
import { EmptyState } from "@/components/empty-state";
import { api } from "@/lib/api";

type CopyRow = { channel: string; body: string };
type AssetRow = { kind: string; channel: string; format: string; name: string; relPath: string };
type LibraryItem = {
  id: string;
  title: string;
  copies: CopyRow[];
  assets: AssetRow[];
  compose?: string;
};

const CHANNEL: Record<string, string> = {
  instagram: "اینستاگرام",
  telegram: "تلگرام",
  whatsapp: "واتساپ",
};

function channelLabel(channel: string) {
  return CHANNEL[channel] || "متن";
}

function composeLabel(status?: string) {
  if (status === "running") return "در حال ساخت";
  if (status === "ready") return "ساخته شد";
  if (status === "failed") return "ساخت کامل نشد";
  return "";
}

function isPicture(asset: AssetRow) {
  const name = asset.name.toLowerCase();
  return asset.kind === "video" || name.endsWith(".png") || name.endsWith(".jpg") || name.endsWith(".jpeg") || name.endsWith(".webp") || name.endsWith(".mp4");
}

function LibraryCard({ item }: { item: LibraryItem }) {
  const status = composeLabel(item.compose);
  return (
    <article className="space-y-3 rounded-2xl border border-line bg-paper p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="truncate text-base font-bold">{item.title}</h2>
        {status ? <p className="shrink-0 text-xs text-warm">{status}</p> : null}
      </div>
      {item.copies.map((copy) => (
        <div key={`${item.id}-${copy.channel}`}>
          <p className="text-xs text-muted">{channelLabel(copy.channel)}</p>
          <p className="mt-1 whitespace-pre-wrap text-sm leading-7 text-ink">{copy.body}</p>
        </div>
      ))}
      {item.assets.length ? (
        <ul className="space-y-2">
          {item.assets.map((asset) => (
            <li key={`${item.id}-${asset.relPath || asset.name}`}>
              {asset.relPath && isPicture(asset) ? (
                <AuthMedia campaignId={item.id} relPath={asset.relPath} kind={asset.kind} alt={item.title} />
              ) : (
                <p className="text-sm text-muted">{asset.name}</p>
              )}
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

  useEffect(() => {
    void api<{ items: LibraryItem[]; drafts: LibraryItem[] }>("/studio/content")
      .then((data) => {
        setItems(data.items || []);
        setDrafts(data.drafts || []);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "خطا"));
  }, []);

  const empty = !items.length && !drafts.length;
  return (
    <div className="h-full space-y-3 overflow-y-auto px-4 py-3">
      {error ? (
        <p className="text-sm text-danger" role="alert">
          {error}
        </p>
      ) : null}
      {empty && !error ? (
        <EmptyState title="هنوز محتوایی نساخته‌ای" detail="از چت استودیو بگو چه پستی می‌خواهی." />
      ) : null}
      {items.map((item) => (
        <LibraryCard key={item.id} item={item} />
      ))}
      {drafts.map((item) => (
        <LibraryCard key={item.id} item={item} />
      ))}
    </div>
  );
}
