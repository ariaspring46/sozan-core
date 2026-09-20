"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
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
      header={
        <div>
          <Link className="text-sm text-warm" href="/inbox">
            بازگشت
          </Link>
          <h1 className="text-lg font-bold">{thread?.sender || "گفتگو"}</h1>
          <p className="text-sm text-muted">
            {thread?.platformLabel}
            {modeLabel ? ` · ${modeLabel}` : ""}
          </p>
          <button
            type="button"
            className="mt-1 text-xs text-warm disabled:opacity-50"
            disabled={pausing || !thread}
            onClick={() => void togglePaused()}
          >
            {thread?.paused ? "پاسخ خودکار این گفتگو خاموش است · روشن کن" : "پاسخ خودکار این گفتگو را خاموش کن"}
          </button>
        </div>
      }
    >
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
