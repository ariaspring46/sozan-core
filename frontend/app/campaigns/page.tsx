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
  const [isAdmin, setIsAdmin] = useState(false);

  async function load() {
    const data = await api<Campaign[]>("/campaigns");
    setItems(data);
    setReady(true);
  }

  useEffect(() => {
    void api<{ isAdmin?: boolean }>("/auth/me")
      .then((me) => setIsAdmin(Boolean(me.isAdmin)))
      .catch(() => undefined);
  }, []);

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
    <main className="h-full space-y-4 overflow-y-auto p-4 [&>*]:mx-auto [&>*]:max-w-3xl">
      <StudioNav current="campaigns" />
      {isAdmin ? (
      <details className="rounded-2xl bg-canvas px-4 py-3 text-sm shadow-card">
        <summary className="flex min-h-11 cursor-pointer items-center text-muted">ورود کمپین از پوشهٔ دیسک (فقط مدیر)</summary>
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
      ) : null}
      {error ? <p className="text-sm text-danger" role="alert">{error}</p> : null}
      {!ready && !error ? <p className="text-sm text-muted">در حال خواندن…</p> : null}
      {ready && items.length === 0 && !error ? (
        <EmptyState
          title="کمپینی نیست"
          detail="از چت بگو چه پستی می‌خواهی، یا اگر پوشه روی دیسک داری شناسه را بالا بگذار."
          action={
            <Link
              href="/chat"
              className="inline-flex min-h-11 items-center rounded-xl bg-accentStrong px-4 text-sm text-onAccent"
            >
              رفتن به چت
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
                <p className="wrap-any text-lg font-medium leading-8">{c.title || "کمپین بدون نام"}</p>
                {c.subtitle ? <p className="wrap-any text-sm leading-6 text-muted">{c.subtitle}</p> : null}
                <p className="mt-1 text-xs text-muted">
                  {(c.copies?.length || 0).toLocaleString("fa-IR")} متن · {(c.assets?.length || 0).toLocaleString("fa-IR")} رسانه
                </p>
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
