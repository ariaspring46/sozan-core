"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, Campaign } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { AppShell } from "@/components/app-shell";
import { StudioNav } from "@/components/studio-nav";
import { EmptyState } from "@/components/empty-state";

export default function CampaignsPage() {
  const [items, setItems] = useState<Campaign[]>([]);
  const [slug, setSlug] = useState("");
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);

  async function load() {
    const data = await api<Campaign[]>("/campaigns");
    setItems(data);
    setReady(true);
  }

  useEffect(() => {
    void load().catch((err) => {
      setError(err.message);
      setReady(true);
    });
  }, []);

  async function importSlug() {
    setError("");
    try {
      await api("/campaigns/import", { method: "POST", body: JSON.stringify({ slug }) });
      setSlug("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    }
  }

  return (
    <AppShell
      header={
        <div>
          <p className="text-sm text-muted">استودیو</p>
          <h1 className="text-lg font-bold">کمپین‌ها</h1>
        </div>
      }
    >
    <main className="h-full space-y-4 overflow-y-auto p-4">
      <StudioNav current="campaigns" />
      <details className="rounded-2xl bg-canvas px-4 py-3 text-sm shadow-card">
        <summary className="cursor-pointer text-muted">ورود کمپین از پوشهٔ دیسک</summary>
        <div className="mt-3 flex flex-col gap-3 sm:flex-row">
          <Input
            placeholder="شناسه روی دیسک"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
          />
          <Button type="button" onClick={() => void importSlug()}>
            ورود از پوشه
          </Button>
        </div>
      </details>
      {error ? <p className="text-sm text-danger">{error}</p> : null}
      {!ready && !error ? <p className="text-sm text-muted">در حال خواندن…</p> : null}
      {ready && items.length === 0 && !error ? (
        <EmptyState
          title="کمپینی نیست"
          detail="از چت استودیو پست بساز، یا اگر پوشه روی دیسک داری شناسه را بالا بگذار."
          action={
            <Link
              href="/studio"
              className="inline-flex min-h-11 items-center rounded-xl bg-accent px-4 text-sm text-onAccent"
            >
              رفتن به چت استودیو
            </Link>
          }
        />
      ) : null}
      {items.length > 0 ? (
      <ul className="space-y-3">
        {items.map((c) => (
          <li key={c.id}>
            <Link href={`/campaigns/${c.id}`}>
              <Card className="hover:border-accent">
                <p className="text-sm text-muted">{c.slug}</p>
                <p className="text-lg font-medium">{c.title}</p>
                <p className="text-sm text-muted">{c.pillar}</p>
              </Card>
            </Link>
          </li>
        ))}
      </ul>
      ) : null}
    </main>
    </AppShell>
  );
}
