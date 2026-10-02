"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { ChannelAlert } from "@/components/channel-alert";
import { GettingStarted } from "@/components/getting-started";
import { ChatThread, type ChatMsg } from "@/components/chat-thread";
import type { PublishPayload, PublishTarget, StudioCaptions } from "@/components/studio-publish";
import { api } from "@/lib/api";
import { emptyIdempotencySlot, finishIdempotencyKey, takeIdempotencyKey } from "@/lib/idempotency";

type ThreadRow = { id: string; title: string; at?: number };

type ChatPayload = {
  messages: ChatMsg[];
  pendingConfirm?: { id: string; tool?: string; summary?: string } | null;
  brand?: string;
  notice?: string;
  threadId?: string;
  threads?: ThreadRow[];
};

function welcomeLines(brand: string) {
  const name = brand.trim();
  return [
    name ? `سلام، من سوزانم — برای ${name}.` : "سلام، من سوزانم.",
    "فروشگاه، محتوا یا دایرکت را همین‌جا بگو.",
    "تغییر تنظیمات همین‌جا با تأیید یا انصراف بسته می‌شود.",
  ];
}

/** نمونه‌جمله‌هایی که سوزان واقعاً انجام می‌دهد؛ در چت خالی تایپ می‌شوند. */
const CHAT_HINTS = [
  "برای انگشتر نقره یک پست اینستاگرام بساز",
  "رنگ دکمه‌های فروشگاه را زرشکی کن",
  "حس فروشگاه را لوکس و خلوت کن",
  "یک بخش درباره ما به سایت اضافه کن",
  "برای تخفیف یلدا پست بساز",
  "دایرکت‌های اینستاگرام را خودکار جواب بده",
  "دستبند چرم را با قیمت ۴۵۰٬۰۰۰ تومان اضافه کن",
  "دامنهٔ فروشگاه من چیه؟",
  "اینستاگرام وصل هست یا نه؟",
  "تو چه کارهایی می‌توانی بکنی؟",
];

const STUDIO_ASPECTS = [
  { id: "post", label: "پست ۴:۵", word: "" },
  { id: "square", label: "مربع", word: "مربع" },
  { id: "story", label: "استوری/ریلز", word: "استوری" },
] as const;

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [pendingConfirm, setPendingConfirm] = useState<ChatPayload["pendingConfirm"]>(null);
  const [brand, setBrand] = useState("");
  const [threadId, setThreadId] = useState("");
  const [threads, setThreads] = useState<ThreadRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [publishTargets, setPublishTargets] = useState<PublishTarget[]>([]);
  const chatKey = useRef(emptyIdempotencySlot());
  const epoch = useRef(0);
  const busyRef = useRef(false);
  const threadRef = useRef("");

  const apply = (data: ChatPayload) => {
    setMessages(data.messages || []);
    setPendingConfirm(data.pendingConfirm || null);
    setBrand(data.brand || "");
    if (data.threadId) {
      setThreadId(data.threadId);
      threadRef.current = data.threadId;
    }
    if (data.threads) setThreads(data.threads);
  };

  const load = useCallback(async (id?: string) => {
    const seen = epoch.current;
    const wanted = id || threadRef.current;
    const path = wanted ? `/chat?threadId=${encodeURIComponent(wanted)}` : "/chat";
    const data = await api<ChatPayload>(path);
    if (seen !== epoch.current) return;
    apply(data);
  }, []);

  useEffect(() => {
    void load().catch((err) => setError(err instanceof Error ? err.message : "خطا"));
    void api<{ targets?: PublishTarget[] }>("/studio")
      .then((data) => setPublishTargets(data.targets || []))
      .catch(() => setPublishTargets([]));
  }, [load]);

  useEffect(() => {
    const composing = messages.some((msg) => msg.compose?.status === "running");
    if (!composing) return;
    const timer = window.setInterval(() => {
      if (busyRef.current) return;
      void load().catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [messages, load]);

  async function send(text: string, file?: File, confirmId?: string, cancelId?: string) {
    const seen = ++epoch.current;
    busyRef.current = true;
    setBusy(true);
    setPending(confirmId || cancelId ? "" : text || file?.name || "پیوست");
    setError("");
    setNotice("");
    const current = threadRef.current;
    const stamp = `${current}\0${text}\0${file?.name || ""}:${file?.size || 0}\0${confirmId || ""}\0${cancelId || ""}`;
    const key = takeIdempotencyKey(chatKey.current, stamp);
    try {
      let data: ChatPayload;
      if (file) {
        const body = new FormData();
        body.set("text", text);
        body.set("file", file);
        if (confirmId) body.set("confirmId", confirmId);
        if (cancelId) body.set("cancelId", cancelId);
        if (current) body.set("threadId", current);
        data = await api<ChatPayload>("/chat", {
          method: "POST",
          headers: { "Idempotency-Key": key },
          body,
        });
      } else {
        data = await api<ChatPayload>("/chat", {
          method: "POST",
          headers: { "Idempotency-Key": key },
          body: JSON.stringify({
            text,
            confirmId: confirmId || "",
            cancelId: cancelId || "",
            threadId: current,
          }),
        });
      }
      finishIdempotencyKey(chatKey.current);
      if (seen === epoch.current) {
        apply(data);
        if (data.notice) setNotice(data.notice);
      }
    } catch (err) {
      if (seen !== epoch.current) return;
      finishIdempotencyKey(chatKey.current, err);
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      if (seen !== epoch.current) return;
      busyRef.current = false;
      setPending("");
      setBusy(false);
    }
  }

  async function openThread(id: string) {
    epoch.current += 1;
    chatKey.current = emptyIdempotencySlot();
    threadRef.current = id;
    setThreadId(id);
    setNotice("");
    setError("");
    await load(id);
  }

  async function startThread() {
    epoch.current += 1;
    chatKey.current = emptyIdempotencySlot();
    setNotice("");
    setError("");
    const data = await api<ChatPayload>("/chat/threads", { method: "POST" });
    apply(data);
  }

  async function publishStudio(payload: PublishPayload) {
    return api<{ skipped?: boolean; message?: string }>("/studio/publish", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify(payload),
    });
  }

  async function saveCaptions(payload: { messageId: string; captions: StudioCaptions }) {
    const data = await api<{ messages?: ChatMsg[] }>("/studio/caption", {
      method: "PATCH",
      body: JSON.stringify({ messageId: payload.messageId, captions: payload.captions }),
    });
    if (data.messages) setMessages(data.messages);
  }

  async function regenerateStudio(payload: {
    messageId: string;
    campaignId?: string;
    part: "image" | "caption";
    file?: File;
  }) {
    const key = crypto.randomUUID();
    if (payload.file) {
      const body = new FormData();
      body.set("messageId", payload.messageId);
      body.set("part", payload.part);
      body.set("file", payload.file);
      await api("/studio/regenerate", { method: "POST", headers: { "Idempotency-Key": key }, body });
    } else {
      await api("/studio/regenerate", {
        method: "POST",
        headers: { "Idempotency-Key": key },
        body: JSON.stringify({ messageId: payload.messageId, part: payload.part }),
      });
    }
    await load();
  }

  return (
    <AppShell
      header={
        <div className="flex min-w-0 items-center gap-2">
          <div className="shrink-0">
            <p className="text-sm text-muted">گفتگو</p>
            <h1 className="whitespace-nowrap text-lg font-bold">سوزان</h1>
          </div>
          <div className="min-w-0 flex-1" />
          {threads.length ? (
            <label className="sr-only" htmlFor="sozan-thread">
              گفتگوها
            </label>
          ) : null}
          {threads.length ? (
            <select
              id="sozan-thread"
              className="min-h-11 min-w-0 max-w-[9rem] rounded-xl border border-line bg-canvas px-2 text-sm text-ink sm:max-w-[14rem]"
              value={threadId}
              onChange={(event) => void openThread(event.target.value).catch((err) => setError(err instanceof Error ? err.message : "خطا"))}
            >
              {threads.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.title}
                </option>
              ))}
            </select>
          ) : null}
          <button
            type="button"
            className="inline-flex min-h-11 shrink-0 items-center rounded-xl border border-line px-3 text-sm text-warm"
            onClick={() => void startThread().catch((err) => setError(err instanceof Error ? err.message : "خطا"))}
          >
            گفتگوی تازه
          </button>
        </div>
      }
    >
      <div className="sozan-chat flex h-full flex-col">
        <ChannelAlert />
        <GettingStarted />
        {error ? (
          <p className="px-4 pt-3 text-sm text-danger" role="alert">
            {error}
          </p>
        ) : null}
        {notice ? (
          <p className="px-4 pt-3 text-sm text-warm" role="status">
            {notice}
          </p>
        ) : null}
        <div className="min-h-0 flex-1">
          <ChatThread
            messages={messages}
            busy={busy}
            pendingText={pending}
            welcome
            welcomeLines={welcomeLines(brand)}
            hints={CHAT_HINTS}
            aspects={STUDIO_ASPECTS}
            placeholder="به سوزان بگو…"
            persona="سوزان"
            showTime
            sanitize
            confirmId={pendingConfirm?.id || ""}
            onConfirm={(id) => void send("", undefined, id)}
            onCancel={(id) => void send("", undefined, undefined, id)}
            onSend={async (payload) => {
              await send(payload.text, payload.file);
            }}
            publishTargets={publishTargets}
            onPublish={publishStudio}
            onSaveCaptions={saveCaptions}
            onRegenerate={regenerateStudio}
          />
        </div>
      </div>
    </AppShell>
  );
}
