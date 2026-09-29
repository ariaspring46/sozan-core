"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { ChannelAlert } from "@/components/channel-alert";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/empty-state";
import { api } from "@/lib/api";
import { formatWhen } from "@/lib/digits";
import { cn } from "@/lib/utils";

type Thread = {
  id: string;
  platform: string;
  platformLabel: string;
  sender: string;
  lastText: string;
  count: number;
  pending?: boolean;
  delivered?: boolean;
  paused?: boolean;
  handoffReason?: string;
  unread?: number;
  lastRole?: string;
  updatedAt?: number;
};

type InboxSnap = {
  threads: Thread[];
  autoReply?: string;
  autoReplyMax?: string;
  autoReplyChoice?: string;
  planLabel?: string;
  dmSync?: boolean;
};

const MODES = [
  { id: "", label: "خاموش" },
  { id: "draft", label: "پیش‌نویس" },
  { id: "send", label: "ارسال خودکار" },
] as const;

const FILTERS = [
  { id: "", label: "همه" },
  { id: "unread", label: "خوانده‌نشده" },
  { id: "pending", label: "منتظر شما" },
] as const;

const PLATFORMS = [
  { id: "", label: "همه کانال‌ها" },
  { id: "instagram", label: "اینستاگرام" },
  { id: "telegram", label: "تلگرام" },
] as const;

const RANK: Record<string, number> = { "": 0, draft: 1, send: 2 };

function preview(thread: Thread) {
  const text = thread.lastText || "بدون متن";
  if (thread.lastRole === "draft") return `پیش‌نویس: ${text}`;
  if (thread.lastRole === "outbound" || thread.lastRole === "failed") return `شما: ${text}`;
  return text;
}

export default function InboxPage() {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [autoReply, setAutoReply] = useState("");
  const [autoReplyMax, setAutoReplyMax] = useState("");
  const [planLabel, setPlanLabel] = useState("");
  const [dmSync, setDmSync] = useState(true);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncNote, setSyncNote] = useState("");
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("");
  const [platform, setPlatform] = useState("");
  const qRef = useRef("");
  const seq = useRef(0);
  const mutating = useRef(false);

  const load = useCallback(async () => {
    if (mutating.current || (typeof document !== "undefined" && document.hidden)) return;
    const n = ++seq.current;
    const params = new URLSearchParams();
    if (qRef.current.trim()) params.set("q", qRef.current.trim());
    if (filter) params.set("filter", filter);
    if (platform) params.set("platform", platform);
    const qs = params.toString();
    const data = await api<InboxSnap>(`/inbox${qs ? `?${qs}` : ""}`);
    if (n !== seq.current) return;
    setThreads(data.threads || []);
    setAutoReply(data.autoReplyChoice ?? data.autoReply ?? "");
    setAutoReplyMax(data.autoReplyMax || "");
    setPlanLabel(data.planLabel || "");
    setDmSync(data.dmSync !== false);
    setError("");
    setLoaded(true);
  }, [filter, platform]);

  useEffect(() => {
    qRef.current = q;
  }, [q]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load().catch((err) => {
        setError(err instanceof Error ? err.message : "خطا");
        setLoaded(true);
      });
    }, q ? 300 : 0);
    return () => window.clearTimeout(timer);
  }, [load, q]);

  useEffect(() => {
    const tick = () => void load().catch(() => undefined);
    const timer = window.setInterval(tick, 4000);
    const onVis = () => {
      if (!document.hidden) tick();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [load]);

  async function setMode(next: string) {
    mutating.current = true;
    setSaving(true);
    setError("");
    try {
      const data = await api<InboxSnap>("/inbox/settings", {
        method: "PATCH",
        body: JSON.stringify({ autoReply: next }),
      });
      setAutoReply(data.autoReplyChoice ?? data.autoReply ?? next);
      setAutoReplyMax(data.autoReplyMax || autoReplyMax);
      setThreads(data.threads || threads);
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      mutating.current = false;
      setSaving(false);
    }
  }

  async function syncNow() {
    mutating.current = true;
    setSyncing(true);
    setError("");
    setSyncNote("");
    try {
      const data = await api<InboxSnap & { imported?: number; hint?: string; error?: string; ok?: boolean }>(
        "/inbox/sync",
        { method: "POST" },
      );
      setThreads(data.threads || threads);
      setAutoReply(data.autoReplyChoice ?? data.autoReply ?? autoReply);
      setAutoReplyMax(data.autoReplyMax || autoReplyMax);
      setDmSync(data.dmSync !== false);
      if (data.error) setError(data.error);
      const imported = Number(data.imported || 0);
      if (imported > 0) setSyncNote(`${imported.toLocaleString("fa-IR")} پیام تازه آمد.`);
      else if (data.hint) setSyncNote(data.hint);
      else if (!data.error) setSyncNote("پیام تازه‌ای نبود.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      mutating.current = false;
      setSyncing(false);
    }
  }

  return (
    <AppShell
      header={
        <div>
          <p className="text-sm text-muted">صندوق</p>
          <h1 className="text-lg font-bold">پیام مشتری‌ها</h1>
        </div>
      }
    >
      <div className="h-full space-y-3 overflow-y-auto p-4">
        <ChannelAlert inset={false} />
        <section aria-label="پاسخ به دایرکت" className="space-y-2 rounded-2xl border border-line/70 bg-paper p-3">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-bold">پاسخ سوزان به دایرکت</h2>
            {planLabel ? <span className="text-[11px] text-muted">پلن {planLabel}</span> : null}
          </div>
          <div className="flex gap-1 rounded-xl bg-canvas p-1" role="radiogroup" aria-label="حالت پاسخ">
            {MODES.map((mode) => {
              const locked = RANK[mode.id] > RANK[autoReplyMax || ""];
              const active = autoReply === mode.id;
              return (
                <button
                  key={mode.id || "off"}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  disabled={saving || locked}
                  title={locked ? `در پلن ${mode.id === "send" ? "پرو مکس" : "پرو"}` : undefined}
                  onClick={() => void setMode(mode.id)}
                  className={cn(
                    "min-h-10 flex-1 rounded-lg px-2 text-xs",
                    active ? "bg-accentStrong font-bold text-onAccent" : "text-muted",
                    locked && "opacity-40",
                  )}
                >
                  {mode.label}
                  {locked ? " 🔒" : ""}
                </button>
              );
            })}
          </div>
          <p className="text-xs leading-6 text-muted">
            {autoReply === "send"
              ? "سوزان خودش جواب مشتری را می‌فرستد."
              : autoReply === "draft"
                ? "سوزان جواب را می‌نویسد؛ تو با یک لمس می‌فرستی."
                : "جواب‌ها را خودت می‌نویسی."}
            {autoReplyMax !== "send" ? (
              <>
                {" "}
                <Link href="/more/settings" className="text-warm underline-offset-4 hover:underline">
                  {autoReplyMax === "draft" ? "ارسال خودکار در پرو مکس" : "پیش‌نویس و ارسال خودکار در پلن‌های پولی"}
                </Link>
              </>
            ) : null}
          </p>
        </section>
        {!dmSync ? (
          <Card>
            <p className="text-sm">همگام‌سازی دایرکت در این پلن خاموش است. پیام‌های جدید از اینستاگرام و تلگرام نمی‌آیند.</p>
          </Card>
        ) : (
          <button
            type="button"
            disabled={syncing}
            onClick={() => void syncNow()}
            className="min-h-11 w-full rounded-2xl border border-line/80 bg-paper px-3 text-sm text-warm disabled:opacity-50"
          >
            {syncing ? "در حال گرفتن پیام‌های تازه…" : "گرفتن پیام‌های تازه"}
          </button>
        )}
        {syncNote ? <p className="text-sm text-muted">{syncNote}</p> : null}
        <input
          className="min-h-11 w-full rounded-2xl border border-line/80 bg-paper px-3 text-[16px] outline-none"
          value={q}
          placeholder="جستجوی نام یا متن"
          aria-label="جستجوی گفتگو"
          onChange={(event) => setQ(event.target.value)}
        />
        <div className="flex flex-wrap gap-1">
          {FILTERS.map((item) => (
            <button
              key={item.id || "all"}
              type="button"
              onClick={() => setFilter(item.id)}
              className={cn(
                "min-h-9 rounded-full px-3 text-xs",
                filter === item.id ? "bg-accentStrong text-onAccent" : "border border-line/70 text-muted",
              )}
            >
              {item.label}
            </button>
          ))}
          {PLATFORMS.map((item) => (
            <button
              key={item.id || "plat"}
              type="button"
              onClick={() => setPlatform(item.id)}
              className={cn(
                "min-h-9 rounded-full px-3 text-xs",
                platform === item.id ? "bg-accentStrong text-onAccent" : "border border-line/70 text-muted",
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
        {error ? (
          <p className="text-sm text-danger" role="alert">
            {error}
          </p>
        ) : null}
        {!loaded ? (
          <div className="space-y-2" aria-busy="true">
            {[0, 1, 2].map((item) => (
              <div key={item} className="h-24 animate-pulse rounded-2xl bg-paper/60" />
            ))}
          </div>
        ) : threads.length === 0 ? (
          <EmptyState
            title={q || filter || platform ? "گفتگویی با این فیلتر نیست" : "هنوز پیامی نیامده"}
            detail={q || filter || platform ? "فیلتر را بردار یا عبارت دیگری بجو." : "حساب کانال را وصل کن تا پیام مشتری اینجا بیاید."}
            action={
              q || filter || platform ? undefined : (
                <Link
                  href="/more/channels"
                  className="inline-flex min-h-11 items-center rounded-xl bg-accentStrong px-4 text-sm text-onAccent"
                >
                  وصل کردن کانال
                </Link>
              )
            }
          />
        ) : (
          <ul className="space-y-2">
            {threads.map((thread) => (
              <li key={thread.id}>
                <Link href={`/inbox/${thread.id}`}>
                  <Card className="hover:border-accent">
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-xs text-warm">{thread.platformLabel}</p>
                      <p className="text-[11px] text-muted">{formatWhen(thread.updatedAt || 0)}</p>
                    </div>
                    <div className="mt-0.5 flex items-center gap-2">
                      <p className="font-medium">{thread.sender}</p>
                      {thread.unread ? (
                        <span className="inline-flex min-w-5 items-center justify-center rounded-full bg-accentStrong px-1.5 text-[11px] text-onAccent">
                          {Number(thread.unread).toLocaleString("fa-IR")}
                        </span>
                      ) : null}
                      {thread.handoffReason ? (
                        <span className="text-[11px] text-warm">منتظر شما</span>
                      ) : thread.paused ? (
                        <span className="text-[11px] text-warm">پاسخ خودکار متوقف</span>
                      ) : null}
                    </div>
                    <p className="truncate text-sm text-muted">{preview(thread)}</p>
                    {thread.lastRole === "draft" ? (
                      <p className="text-[11px] text-warm">پیش‌نویس هوش مصنوعی</p>
                    ) : thread.lastRole === "failed" ? (
                      <p className="text-[11px] text-danger">ارسال نشد</p>
                    ) : thread.pending ? (
                      <p className="text-[11px] text-warm">پیش‌نویس یا ارسال ناموفق</p>
                    ) : null}
                  </Card>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </AppShell>
  );
}
