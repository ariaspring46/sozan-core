"use client";

import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Mic, Paperclip, Square } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ChatAttach } from "@/components/chat-attach";
import { StudioPublishCard, type PublishPayload, type PublishTarget, type StudioAttachment, type StudioCaptions } from "@/components/studio-publish";
import { formatWhen } from "@/lib/digits";

export type ChatMsg = {
  id: string;
  role: "user" | "assistant";
  text: string;
  at: number;
  kind?: string;
  campaignId?: string;
  platform?: string;
  platformLabel?: string;
  sender?: string;
  mediaKind?: string;
  mediaName?: string;
  attachments?: StudioAttachment[];
  captions?: StudioCaptions;
  published?: Record<string, number>;
  compose?: { status?: string; error?: string; jobId?: string };
  delivered?: boolean;
  status?: string;
  error?: string;
};

export type ChatSend = { text: string; file?: File };

const SHOP_DENY = /seed phrase|bitcoin|private key|mnemonic|Traceback|FAIL:/i;
const SHOP_WELCOME = [
  "۱) حس فروشگاه را بگو.",
  "۲) کالا و قیمت تومان را کامل کن.",
  "۳) وقتی آماده بودی بنویس بساز.",
];

export function sanitizeShopText(text: string, enabled?: boolean) {
  if (!enabled) return text;
  if (SHOP_DENY.test(text || "")) return "پیام نامعتبر حذف شد";
  return text;
}

const WAIT_LINES = ["دارم فکر می‌کنم…", "یک لحظه…", "جواب را می‌چینم…"];

function WaitSignal({ label }: { label: string }) {
  return (
    <div className="ms-auto flex max-w-[85%] items-center gap-3 rounded-2xl border border-line/70 bg-paper px-4 py-2.5">
      <span className="flex items-center gap-1">
        <span className="sozan-dot h-1.5 w-1.5 rounded-full bg-signal" />
        <span className="sozan-dot h-1.5 w-1.5 rounded-full bg-signal" />
        <span className="sozan-dot h-1.5 w-1.5 rounded-full bg-signal" />
      </span>
      <p className="text-xs text-warm">{label}</p>
    </div>
  );
}

export function ChatThread({
  messages,
  busy,
  placeholder,
  onSend,
  livePanel,
  pendingText,
  tone = "default",
  allowMedia = true,
  publishTargets,
  onPublish,
  onRegenerate,
  onApproveDraft,
  onDiscardFailed,
  onSaveCaptions,
  onEditDraft,
  showTime = false,
  sanitize = false,
  welcome = false,
}: {
  messages: ChatMsg[];
  busy: boolean;
  placeholder: string;
  onSend: (payload: ChatSend) => Promise<void> | void;
  livePanel?: ReactNode;
  pendingText?: string;
  tone?: "default" | "future";
  allowMedia?: boolean;
  publishTargets?: PublishTarget[];
  onPublish?: (payload: PublishPayload) => Promise<{ skipped?: boolean; message?: string } | void>;
  onRegenerate?: (payload: { messageId: string; campaignId?: string; part: "image" | "caption"; file?: File }) => Promise<void>;
  onApproveDraft?: (payload: { messageId: string; text: string }) => Promise<void>;
  onDiscardFailed?: (payload: { messageId: string }) => Promise<void>;
  onSaveCaptions?: (payload: { messageId: string; captions: StudioCaptions }) => void | Promise<void>;
  onEditDraft?: (payload: { messageId: string; text: string }) => void;
  sanitize?: boolean;
  welcome?: boolean;
  showTime?: boolean;
}) {
  const [draft, setDraft] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [recording, setRecording] = useState(false);
  const [micError, setMicError] = useState("");
  const [waitLine, setWaitLine] = useState(WAIT_LINES[0]);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const fileRef = useRef<HTMLInputElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const future = tone === "future";
  const canSend = Boolean((draft.trim() || (allowMedia && file)) && !busy);

  const stickToEnd = () => {
    if (!stickRef.current) return;
    const el = scrollerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  };

  useEffect(() => {
    stickToEnd();
  }, [messages, busy, pendingText, file]);

  useEffect(() => {
    const vv = window.visualViewport;
    vv?.addEventListener("resize", stickToEnd);
    return () => vv?.removeEventListener("resize", stickToEnd);
  }, []);

  useEffect(() => {
    if (!busy || !future) return;
    let index = 0;
    const timer = window.setInterval(() => {
      index = (index + 1) % WAIT_LINES.length;
      setWaitLine(WAIT_LINES[index]);
    }, 2200);
    return () => window.clearInterval(timer);
  }, [busy, future]);

  useEffect(() => {
    return () => {
      recorderRef.current?.stream.getTracks().forEach((track) => track.stop());
    };
  }, []);

  async function toggleVoice() {
    setMicError("");
    if (recording) {
      recorderRef.current?.stop();
      return;
    }
    if (typeof MediaRecorder === "undefined") {
      setMicError("ضبط صدا در این مرورگر نیست.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        const ext = blob.type.includes("ogg") ? "ogg" : "webm";
        setFile(new File([blob], `voice.${ext}`, { type: blob.type || "audio/webm" }));
        setRecording(false);
        recorderRef.current = null;
      };
      recorderRef.current = recorder;
      recorder.start();
      setRecording(true);
    } catch {
      setMicError("میکروفون در دسترس نیست.");
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSend) return;
    const text = draft.trim();
    const attached = file || undefined;
    try {
      await onSend({ text, file: attached });
      setDraft("");
      setFile(null);
    } catch {
      setDraft(text);
      setFile(attached || null);
    }
  }

  return (
    <div className="flex h-full flex-col bg-transparent">
      {livePanel}
      <div
        ref={scrollerRef}
        className="min-h-0 flex-1 overflow-y-auto"
        onScroll={() => {
          const el = scrollerRef.current;
          if (!el) return;
          stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 96;
        }}
      >
        <div className="space-y-3 px-4 py-5">
          {messages.length === 0 && !pendingText ? (
            welcome ? (
              <div className="space-y-2 pt-8 text-center text-sm leading-7 text-muted">
                {SHOP_WELCOME.map((line) => (
                  <p key={line}>{line}</p>
                ))}
              </div>
            ) : (
              <p className="pt-10 text-center text-sm leading-7 text-muted">پیام را پایین بنویس.</p>
            )
          ) : (
            messages.map((msg) => (
              <article
                key={msg.id}
                className={cn(
                  "max-w-[85%] px-3.5 py-2.5 text-sm leading-7",
                  msg.kind === "build"
                    ? "ms-auto rounded-2xl border border-line/70 bg-canvas text-warm"
                    : msg.role === "user"
                      ? "ms-0 rounded-2xl bg-accent text-onAccent"
                      : "ms-auto rounded-2xl border border-line/60 bg-paper text-ink",
                )}
              >
                {msg.platformLabel || msg.platform || msg.sender ? (
                  <p className="mb-1 text-[11px] text-warm">
                    {[msg.platformLabel || msg.platform, msg.sender].filter(Boolean).join(" · ")}
                  </p>
                ) : null}
                {msg.text ? <p className="whitespace-pre-wrap">{sanitizeShopText(msg.text, sanitize)}</p> : null}
                {showTime && msg.at ? (
                  <p className="mt-1 text-[11px] opacity-70">
                    {formatWhen(msg.at)}
                    {msg.status === "sending"
                      ? " · در حال ارسال…"
                      : msg.kind === "outbound" && (msg.status === "sent" || msg.delivered)
                        ? " · ارسال شد"
                        : ""}
                  </p>
                ) : null}
                {msg.kind === "draft" ? (
                  <div className="mt-2">
                    <p className="text-[11px] text-warm">پیش‌نویس هوش مصنوعی — هنوز ارسال نشده</p>
                    {onApproveDraft ? (
                      <div className="mt-1 flex gap-2">
                        <Button
                          type="button"
                          variant="ghost"
                          className="h-auto py-1 text-xs"
                          disabled={busy}
                          onClick={() => void onApproveDraft({ messageId: msg.id, text: msg.text })}
                        >
                          بفرست
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          className="h-auto py-1 text-xs"
                          disabled={busy}
                          onClick={() => {
                            setDraft(msg.text);
                            onEditDraft?.({ messageId: msg.id, text: msg.text });
                          }}
                        >
                          ویرایش
                        </Button>
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {msg.kind === "failed" || msg.status === "failed" ? (
                  <div className="mt-2">
                    <p className="text-[11px] text-danger" role="alert">
                      {msg.error || "ارسال نشد"}
                    </p>
                    <div className="mt-1 flex gap-2">
                      {onApproveDraft ? (
                        <Button
                          type="button"
                          variant="ghost"
                          className="h-auto py-1 text-xs"
                          onClick={() => void onApproveDraft({ messageId: msg.id, text: msg.text })}
                        >
                          دوباره بفرست
                        </Button>
                      ) : null}
                      {onDiscardFailed ? (
                        <Button
                          type="button"
                          variant="ghost"
                          className="h-auto py-1 text-xs"
                          disabled={busy}
                          onClick={() => void onDiscardFailed({ messageId: msg.id })}
                        >
                          حذف
                        </Button>
                      ) : null}
                    </div>
                  </div>
                ) : null}
                {msg.compose?.status === "running" ? (
                  <WaitSignal label="در حال ساخت تصویر و ویدیو…" />
                ) : null}
                {msg.compose?.status === "failed" ? (
                  <div className="mt-2">
                    <p className="text-[11px] text-danger" role="alert">{msg.compose.error || "ساخت تصویر نشد"}</p>
                    {onRegenerate ? (
                      <Button
                        type="button"
                        variant="ghost"
                        className="mt-1 h-auto py-1 text-xs"
                        onClick={() => void onRegenerate({ messageId: msg.id, campaignId: msg.campaignId, part: "image" })}
                      >
                        دوباره بساز
                      </Button>
                    ) : null}
                  </div>
                ) : null}
                {(msg.attachments?.length
                  ? msg.attachments
                  : msg.mediaKind && msg.mediaName
                    ? [{ kind: msg.mediaKind, name: msg.mediaName }]
                    : []
                ).map((item) => (
                  <ChatAttach key={item.name} kind={item.kind} name={item.name} />
                ))}
                {onPublish && msg.role === "assistant" && (msg.attachments?.length || (msg.mediaKind && msg.mediaName)) ? (
                  <StudioPublishCard
                    campaignId={msg.campaignId}
                    messageId={msg.id}
                    attachments={
                      msg.attachments?.length
                        ? msg.attachments
                        : [{ kind: msg.mediaKind || "image", name: msg.mediaName || "" }]
                    }
                    captions={msg.captions}
                    published={msg.published}
                    targets={publishTargets || []}
                    onPublish={onPublish}
                    onRegenerate={
                      onRegenerate
                        ? (part, file) => onRegenerate({ messageId: msg.id, campaignId: msg.campaignId, part, file })
                        : undefined
                    }
                    onSaveCaptions={
                      onSaveCaptions
                        ? (next) => onSaveCaptions({ messageId: msg.id, captions: next })
                        : undefined
                    }
                  />
                ) : null}
                {msg.campaignId ? (
                  <Link className="mt-1 block text-warm" href={`/campaigns/${msg.campaignId}`}>
                    باز کردن کمپین
                  </Link>
                ) : null}
              </article>
            ))
          )}
          {pendingText ? (
            <article className="ms-0 max-w-[85%] rounded-2xl bg-accent px-3.5 py-2.5 text-sm leading-7 text-onAccent opacity-80">
              <p className="whitespace-pre-wrap">{pendingText}</p>
            </article>
          ) : null}
          {busy ? future ? <WaitSignal label={waitLine} /> : <p className="text-center text-xs text-muted">در حال نوشتن…</p> : null}
        </div>
      </div>
      <form className="shrink-0 space-y-2 border-t border-line/70 bg-canvas px-3 pb-2 pt-2" onSubmit={(event) => void submit(event)}>
        {file ? (
          <div className="flex items-center justify-between gap-2 rounded-2xl border border-line/70 bg-paper px-3 py-2 text-xs text-muted">
            <span className="truncate">{file.type.startsWith("image/") ? "تصویر" : file.type.startsWith("video/") ? "ویدیو" : "صدا"} · {file.name}</span>
            <button type="button" className="text-warm" onClick={() => setFile(null)}>
              حذف
            </button>
          </div>
        ) : null}
        {recording ? <p className="text-xs text-warm">در حال ضبط صدا…</p> : null}
        {micError ? <p className="text-xs text-danger">{micError}</p> : null}
        <div className="flex items-end gap-2 rounded-2xl border border-line/80 bg-paper px-2 py-2">
          {allowMedia ? (
            <>
              <input
                ref={fileRef}
                type="file"
                className="hidden"
                accept="image/*,video/mp4,video/webm,audio/*"
                onChange={(event) => {
                  setFile(event.target.files?.[0] || null);
                  event.target.value = "";
                }}
              />
              <button
                type="button"
                className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-muted"
                aria-label="پیوست تصویر یا ویدیو"
                disabled={busy}
                onClick={() => fileRef.current?.click()}
              >
                <Paperclip size={18} />
              </button>
              <button
                type="button"
                className={cn(
                  "inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl",
                  recording ? "text-danger" : "text-muted",
                )}
                aria-label={recording ? "پایان ضبط" : "ضبط صدا"}
                disabled={busy}
                onClick={() => void toggleVoice()}
              >
                {recording ? <Square size={16} /> : <Mic size={18} />}
              </button>
            </>
          ) : null}
          <textarea
            className="max-h-28 min-h-11 flex-1 resize-none bg-transparent px-1 py-2 text-[16px] leading-6 outline-none"
            rows={1}
            value={draft}
            disabled={busy}
            placeholder={placeholder}
            aria-label={placeholder}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
          />
          <Button type="submit" className="h-auto shrink-0 whitespace-nowrap rounded-xl px-3 py-2" disabled={!canSend}>
            بفرست
          </Button>
        </div>
      </form>
    </div>
  );
}
