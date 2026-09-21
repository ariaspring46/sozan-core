"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { ChatThread, type ChatMsg } from "@/components/chat-thread";
import { api } from "@/lib/api";
import { emptyIdempotencySlot, finishIdempotencyKey, takeIdempotencyKey } from "@/lib/idempotency";

type ChatPayload = {
  messages: ChatMsg[];
  pendingConfirm?: { id: string; tool?: string; summary?: string } | null;
  brand?: string;
};

function welcomeLines(brand: string) {
  const name = brand.trim();
  return [
    name ? `سلام، من سوزانم — برای ${name}.` : "سلام، من سوزانم.",
    "فروشگاه، محتوا یا دایرکت را همین‌جا بگو.",
    "تغییر تنظیمات همین‌جا با تأیید یا انصراف بسته می‌شود.",
  ];
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [pendingConfirm, setPendingConfirm] = useState<ChatPayload["pendingConfirm"]>(null);
  const [brand, setBrand] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const chatKey = useRef(emptyIdempotencySlot());
  const epoch = useRef(0);
  const busyRef = useRef(false);

  const apply = (data: ChatPayload) => {
    setMessages(data.messages || []);
    setPendingConfirm(data.pendingConfirm || null);
    setBrand(data.brand || "");
  };

  const load = useCallback(async () => {
    const seen = epoch.current;
    const data = await api<ChatPayload>("/chat");
    if (seen !== epoch.current) return;
    apply(data);
  }, []);

  useEffect(() => {
    void load().catch((err) => setError(err instanceof Error ? err.message : "خطا"));
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
    const stamp = `${text}\0${file?.name || ""}:${file?.size || 0}\0${confirmId || ""}\0${cancelId || ""}`;
    const key = takeIdempotencyKey(chatKey.current, stamp);
    try {
      let data: ChatPayload;
      if (file) {
        const body = new FormData();
        body.set("text", text);
        body.set("file", file);
        if (confirmId) body.set("confirmId", confirmId);
        if (cancelId) body.set("cancelId", cancelId);
        data = await api<ChatPayload>("/chat", {
          method: "POST",
          headers: { "Idempotency-Key": key },
          body,
        });
      } else {
        data = await api<ChatPayload>("/chat", {
          method: "POST",
          headers: { "Idempotency-Key": key },
          body: JSON.stringify({ text, confirmId: confirmId || "", cancelId: cancelId || "" }),
        });
      }
      finishIdempotencyKey(chatKey.current);
      if (seen === epoch.current) apply(data);
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

  return (
    <AppShell
      header={
        <div>
          <p className="text-sm text-muted">گفتگو</p>
          <h1 className="text-lg font-bold">سوزان</h1>
        </div>
      }
    >
      <div className="sozan-chat flex h-full flex-col">
        {error ? (
          <p className="px-4 pt-3 text-sm text-danger" role="alert">
            {error}
          </p>
        ) : null}
        <div className="min-h-0 flex-1">
          <ChatThread
            messages={messages}
            busy={busy}
            pendingText={pending}
            welcome
            welcomeLines={welcomeLines(brand)}
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
          />
        </div>
      </div>
    </AppShell>
  );
}
