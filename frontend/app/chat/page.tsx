"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { ChannelAlert } from "@/components/channel-alert";
import { GettingStarted } from "@/components/getting-started";
import { ChatThread, type ChatMsg } from "@/components/chat-thread";
import { CHAT_STARTERS, greeting } from "@/components/chat-welcome";
import { ChatHeader, type ThreadRow } from "@/components/chat-header";
import type { PublishPayload, PublishTarget, StudioCaptions } from "@/components/studio-publish";
import { api, timeoutSignal } from "@/lib/api";
import { emptyIdempotencySlot, finishIdempotencyKey, takeIdempotencyKey } from "@/lib/idempotency";

type ChatPayload = {
  messages: ChatMsg[];
  pendingConfirm?: { id: string; tool?: string; summary?: string } | null;
  brand?: string;
  notice?: string;
  threadId?: string;
  threads?: ThreadRow[];
};

const STUDIO_ASPECTS = [
  { id: "post", label: "پست ۴:۵", word: "" },
  { id: "square", label: "مربع", word: "مربع" },
  { id: "story", label: "استوری/ریلز", word: "استوری" },
] as const;

/** کمی بیشتر از بدترین زمان سرور (دو مدل پشت‌سرهم)؛ بعد از آن پیام خطا می‌آید و متن برمی‌گردد. */
const CHAT_TIMEOUT_MS = 100_000;

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [pendingConfirm, setPendingConfirm] = useState<ChatPayload["pendingConfirm"]>(null);
  const [brand, setBrand] = useState("");
  const [threadId, setThreadId] = useState("");
  const [threads, setThreads] = useState<ThreadRow[]>([]);
  const [loaded, setLoaded] = useState(false);
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
    void load()
      .catch((err) => setError(err instanceof Error ? err.message : "خطا"))
      .finally(() => setLoaded(true));
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

  /** true = جواب رسید (یا گفتگو عوض شد)؛ false = ارسال نشد و متن باید به کادر برگردد. */
  async function send(text: string, file?: File, confirmId?: string, cancelId?: string): Promise<boolean> {
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
          signal: timeoutSignal(CHAT_TIMEOUT_MS),
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
          signal: timeoutSignal(CHAT_TIMEOUT_MS),
        });
      }
      finishIdempotencyKey(chatKey.current);
      if (seen === epoch.current) {
        apply(data);
        if (data.notice) setNotice(data.notice);
      }
      return true;
    } catch (err) {
      if (seen !== epoch.current) return true;
      finishIdempotencyKey(chatKey.current, err);
      setError(err instanceof Error ? err.message : "خطا");
      return false;
    } finally {
      if (seen === epoch.current) {
        busyRef.current = false;
        setPending("");
        setBusy(false);
      }
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
      scene
      header={
        <ChatHeader
          busy={busy}
          threads={threads}
          threadId={threadId}
          onOpen={(id) => void openThread(id).catch((err) => setError(err instanceof Error ? err.message : "خطا"))}
          onNew={() => void startThread().catch((err) => setError(err instanceof Error ? err.message : "خطا"))}
          extra={messages.length ? <GettingStarted compact /> : null}
        />
      }
    >
      <div className="flex h-full flex-col">
        <ChannelAlert />
        {messages.length ? null : <GettingStarted />}
        <div className="min-h-0 flex-1">
          <ChatThread
            messages={messages}
            busy={busy}
            loading={!loaded}
            banner={
              error ? (
                <p className="rounded-xl border border-danger/40 bg-paper px-3 py-2 text-sm text-danger" role="alert">
                  {error}
                </p>
              ) : notice ? (
                <p className="rounded-xl border border-line bg-paper px-3 py-2 text-sm text-warm" role="status">
                  {notice}
                </p>
              ) : null
            }
            pendingText={pending}
            welcome
            welcomeLines={greeting(brand)}
            starters={CHAT_STARTERS}
            aspects={STUDIO_ASPECTS}
            placeholder="به سوزان بگو…"
            persona="سوزان"
            showTime
            sanitize
            confirmId={pendingConfirm?.id || ""}
            onConfirm={(id) => void send("", undefined, id)}
            onCancel={(id) => void send("", undefined, undefined, id)}
            onSend={async (payload) => {
              if (!(await send(payload.text, payload.file))) throw new Error("not-sent");
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
