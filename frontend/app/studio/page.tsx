"use client";

import { useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { ChatThread, type ChatMsg } from "@/components/chat-thread";
import { StudioNav } from "@/components/studio-nav";
import type { PublishTarget } from "@/components/studio-publish";
import { api } from "@/lib/api";
import { emptyIdempotencySlot, finishIdempotencyKey, takeIdempotencyKey } from "@/lib/idempotency";

export default function StudioPage() {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [targets, setTargets] = useState<PublishTarget[]>([]);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const chatKey = useRef(emptyIdempotencySlot());
  const publishKey = useRef(emptyIdempotencySlot());
  const regenKey = useRef(emptyIdempotencySlot());

  async function load() {
    const data = await api<{ messages: ChatMsg[]; targets?: PublishTarget[]; composing?: boolean }>("/studio");
    setMessages(data.messages || []);
    setTargets(data.targets || []);
    return data;
  }

  useEffect(() => {
    void load().catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    const composing = messages.some((msg) => msg.compose?.status === "running");
    if (!composing) return;
    const timer = window.setInterval(() => void load().catch(() => undefined), 2000);
    return () => window.clearInterval(timer);
  }, [messages]);

  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === "visible") void load().catch(() => undefined);
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  return (
    <AppShell
      header={
        <div>
          <p className="text-sm text-muted">استودیو</p>
          <h1 className="text-lg font-bold">ساخت پست با چت</h1>
        </div>
      }
    >
      <div className="sozan-chat flex h-full flex-col">
        <div className="px-4 pt-3">
          <StudioNav current="studio" />
        </div>
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
            placeholder="بگو برای اینستاگرام، تلگرام یا واتساپ چه پستی می‌خواهی. تصویر را هم می‌توانی پیوست کنی."
            publishTargets={targets}
            onPublish={async (payload) => {
              const stamp = JSON.stringify(payload);
              const key = takeIdempotencyKey(publishKey.current, stamp);
              try {
                const data = await api<{ ok: boolean; skipped?: boolean; message?: string; messages?: ChatMsg[] }>("/studio/publish", {
                  method: "POST",
                  headers: { "Idempotency-Key": key },
                  body: JSON.stringify(payload),
                });
                if (!data.ok) throw new Error(data.message || "ارسال نشد");
                finishIdempotencyKey(publishKey.current);
                if (data.messages) setMessages(data.messages);
                else {
                  const snap = await api<{ messages: ChatMsg[] }>("/studio");
                  setMessages(snap.messages || []);
                }
                return { skipped: data.skipped, message: data.message };
              } catch (err) {
                finishIdempotencyKey(publishKey.current, err);
                setError(err instanceof Error ? err.message : "ارسال نشد");
                throw err;
              }
            }}
            onSaveCaptions={async ({ messageId, captions }) => {
              try {
                await api("/studio/caption", {
                  method: "PATCH",
                  body: JSON.stringify({ messageId, captions }),
                });
              } catch (err) {
                setError(err instanceof Error ? err.message : "کپشن ذخیره نشد");
                throw err;
              }
            }}
            onRegenerate={async ({ messageId, part, file }) => {
              const stamp = `${messageId}\0${part}\0${file?.name || ""}:${file?.size || 0}`;
              const key = takeIdempotencyKey(regenKey.current, stamp);
              const body = new FormData();
              body.set("messageId", messageId);
              body.set("part", part);
              if (file) body.set("file", file);
              try {
                const data = await api<{ messages: ChatMsg[] }>("/studio/regenerate", {
                  method: "POST",
                  headers: { "Idempotency-Key": key },
                  body,
                });
                finishIdempotencyKey(regenKey.current);
                setMessages(data.messages || []);
              } catch (err) {
                finishIdempotencyKey(regenKey.current, err);
                setError(err instanceof Error ? err.message : "ساخت دوباره نشد");
                throw err;
              }
            }}
            onSend={async (payload) => {
              setBusy(true);
              setPending(payload.text || payload.file?.name || "پیوست");
              setError("");
              const stamp = `${payload.text}\0${payload.file?.name || ""}:${payload.file?.size || 0}`;
              const key = takeIdempotencyKey(chatKey.current, stamp);
              try {
                const body = new FormData();
                body.set("text", payload.text);
                if (payload.file) body.set("file", payload.file);
                const data = await api<{ messages: ChatMsg[] }>("/studio/chat", {
                  method: "POST",
                  headers: { "Idempotency-Key": key },
                  body,
                });
                finishIdempotencyKey(chatKey.current);
                setMessages(data.messages || []);
              } catch (err) {
                finishIdempotencyKey(chatKey.current, err);
                setError(err instanceof Error ? err.message : "خطا");
                throw err;
              } finally {
                setPending("");
                setBusy(false);
              }
            }}
          />
        </div>
      </div>
    </AppShell>
  );
}
