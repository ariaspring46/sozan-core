"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { ChatThread, type ChatMsg } from "@/components/chat-thread";
import { api } from "@/lib/api";
import { emptyIdempotencySlot, finishIdempotencyKey, takeIdempotencyKey } from "@/lib/idempotency";

type Thread = {
  id: string;
  platformLabel: string;
  sender: string;
  pending?: boolean;
  paused?: boolean;
  handoffReason?: string;
};

type InboxSnap = { thread: Thread; messages: ChatMsg[]; autoReply?: string };

export default function InboxThreadPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = params.id;
  const [thread, setThread] = useState<Thread | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [autoReply, setAutoReply] = useState("");
  const [pendingText, setPendingText] = useState("");
  const [pausing, setPausing] = useState(false);
  const [editDraftId, setEditDraftId] = useState("");
  const replyKey = useRef(emptyIdempotencySlot());
  const seq = useRef(0);
  const busyRef = useRef(false);

  useEffect(() => {
    busyRef.current = busy;
  }, [busy]);

  const load = useCallback(async () => {
    if (busyRef.current || (typeof document !== "undefined" && document.hidden)) return;
    const n = ++seq.current;
    try {
      const data = await api<InboxSnap>(`/inbox/${id}`);
      if (n !== seq.current) return;
      setThread(data.thread);
      setMessages(data.messages || []);
      setAutoReply(data.autoReply || "");
      setError("");
    } catch (err) {
      const message = err instanceof Error ? err.message : "خطا";
      if (message.includes("پیدا نشد")) {
        router.replace("/inbox");
        return;
      }
      setError(message);
    }
  }, [id, router]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 4000);
    const onVis = () => {
      if (!document.hidden) void load();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [load]);

  async function sendReply(text: string, draftId = "") {
    const stamp = `${text}\0${draftId}`;
    const key = takeIdempotencyKey(replyKey.current, stamp);
    try {
      const data = await api<InboxSnap>(`/inbox/${id}/reply`, {
        method: "POST",
        headers: { "Idempotency-Key": key },
        body: JSON.stringify({ text, draftId, deliver: true }),
      });
      finishIdempotencyKey(replyKey.current);
      setThread(data.thread);
      setMessages(data.messages || []);
    } catch (err) {
      finishIdempotencyKey(replyKey.current, err);
      throw err;
    }
  }

  async function togglePaused() {
    if (!thread) return;
    setPausing(true);
    setError("");
    try {
      const data = await api<InboxSnap>(`/inbox/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ paused: !thread.paused }),
      });
      setThread(data.thread);
      if (data.messages) setMessages(data.messages);
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setPausing(false);
    }
  }

  const modeLabel = autoReply === "send" ? "پاسخ خودکار" : autoReply === "draft" ? "پیش‌نویس خودکار" : "پاسخ دستی";

  return (
    <AppShell
      scene
      header={
        <div className="flex min-w-0 items-center gap-1">
          <Link
            href="/inbox"
            aria-label="بازگشت به صندوق"
            className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-warm hover:bg-canvas"
          >
            <ChevronRight size={22} aria-hidden />
          </Link>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-lg font-bold" dir="auto">
              {thread?.sender || "گفتگو"}
            </h1>
            <p className="truncate text-sm text-muted">
              {thread?.platformLabel}
              {modeLabel ? ` · ${modeLabel}` : ""}
            </p>
          </div>
        </div>
      }
    >
      <div className="sozan-glass mx-3 flex shrink-0 items-center justify-between gap-3 rounded-2xl px-4 py-1.5">
        <p className="min-w-0 text-sm leading-6 text-muted">
          {thread?.paused ? "پاسخ خودکار این گفتگو خاموش است." : "پاسخ خودکار این گفتگو روشن است."}
        </p>
        <button
          type="button"
          className="inline-flex min-h-11 shrink-0 items-center rounded-xl border border-line px-3 text-sm text-warm disabled:opacity-50"
          disabled={pausing || !thread}
          onClick={() => void togglePaused()}
        >
          {thread?.paused ? "روشن کن" : "خاموش کن"}
        </button>
      </div>
      {thread?.handoffReason ? (
        <p className="shrink-0 bg-accent/10 px-4 py-2 text-sm leading-6 text-warm" role="status">
          منتظر شما · {thread.handoffReason}
        </p>
      ) : null}
      {error ? (
        <p className="shrink-0 px-4 pt-3 text-sm text-danger" role="alert">
          {error}
        </p>
      ) : null}
      <div className="min-h-0 flex-1">
        <ChatThread
          messages={messages}
          busy={busy}
          allowMedia={false}
          showTime
          pendingText={pendingText}
          placeholder="پاسخ را بنویس."
          onApproveDraft={async ({ messageId, text }) => {
            setBusy(true);
            setError("");
            try {
              await sendReply(text, messageId);
              setEditDraftId("");
            } catch (err) {
              setError(err instanceof Error ? err.message : "خطا");
            } finally {
              setBusy(false);
            }
          }}
          onDiscardFailed={async ({ messageId }) => {
            setBusy(true);
            setError("");
            try {
              const data = await api<InboxSnap>(`/inbox/${id}/messages/${messageId}`, { method: "DELETE" });
              setThread(data.thread);
              setMessages(data.messages || []);
            } catch (err) {
              setError(err instanceof Error ? err.message : "خطا");
            } finally {
              setBusy(false);
            }
          }}
          onEditDraft={({ messageId, text }) => {
            setEditDraftId(messageId);
            void text;
          }}
          onSend={async (payload) => {
            setBusy(true);
            setError("");
            setPendingText(payload.text);
            try {
              await sendReply(payload.text, editDraftId);
              setEditDraftId("");
              setPendingText("");
            } catch (err) {
              setPendingText("");
              setError(err instanceof Error ? err.message : "خطا");
              throw err;
            } finally {
              setBusy(false);
            }
          }}
        />
      </div>
    </AppShell>
  );
}
