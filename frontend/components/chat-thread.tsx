"use client";

import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Mic, Paperclip, Square } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ChatAttach } from "@/components/chat-attach";
import { SozanMark } from "@/components/sozan-mark";
import { StudioPublishCard, type PublishPayload, type PublishTarget, type StudioAttachment, type StudioCaptions } from "@/components/studio-publish";
import { formatWhen } from "@/lib/digits";
import { TypingHints } from "@/components/typing-hints";

export type ChatMsg = {
  id: string;
  role: "user" | "assistant";
  text: string;
  at: number;
  kind?: string;
  confirmId?: string;
  options?: string[];
  campaignId?: string;
  platform?: string;
  platformLabel?: string;
  sender?: string;
  mediaKind?: string;
  mediaName?: string;
  attachments?: StudioAttachment[];
  captions?: StudioCaptions;
  published?: Record<string, number>;
  compose?: { status?: string; error?: string; jobId?: string; stage?: string; startedAt?: number };
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

function composeWaitLabel(compose: NonNullable<ChatMsg["compose"]>, now: number): string {
  const started = Number(compose.startedAt || 0);
  const elapsed = started > 0 ? Math.max(0, Math.round(now / 1000 - started)) : 0;
  const clock = elapsed ? ` ${elapsed.toLocaleString("fa-IR")} ثانیه گذشته.` : "";
  if (compose.stage === "layout") return `متن روی عکس چیده می‌شود. چند ثانیه.${clock}`;
  return `عکس در حال ساخته شدن است. معمولاً حدود یک دقیقه.${clock}`;
}

function ComposeWait({ compose }: { compose: NonNullable<ChatMsg["compose"]> }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return <WaitSignal label={composeWaitLabel(compose, now)} />;
}

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
  welcomeLines,
  hints,
  confirmId = "",
  onConfirm,
  onCancel,
  persona = "",
  aspects,
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
  welcomeLines?: string[];
  /** جمله‌های راهنما که در چت خالی تایپ می‌شوند و باد می‌بردشان. */
  hints?: string[];
  confirmId?: string;
  onConfirm?: (confirmId: string) => void;
  onCancel?: (confirmId: string) => void;
  persona?: string;
  showTime?: boolean;
  /** انتخاب‌گر نسبت خروجی استودیو: پست ۴:۵، مربع، استوری. */
  aspects?: readonly { id: string; label: string; word: string }[];
}) {
  const [draft, setDraft] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [recording, setRecording] = useState(false);
  const [micError, setMicError] = useState("");
  const [waitLine, setWaitLine] = useState(WAIT_LINES[0]);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const fileRef = useRef<HTMLInputElement>(null);
  const draftRef = useRef<HTMLTextAreaElement>(null);
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

  const [aspect, setAspect] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSend) return;
    let text = draft.trim();
    const chosen = (aspects || []).find((row) => row.id === aspect);
    if (chosen && chosen.word && !text.includes(chosen.word)) text = `${text} (${chosen.word})`.trim();
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
            welcome || welcomeLines ? (
              <div className="flex min-h-[min(60vh,28rem)] flex-col items-center justify-center gap-6 pt-6">
                <div className="space-y-1 text-center text-sm leading-7 text-muted">
                  {(welcomeLines || SHOP_WELCOME).map((line) => (
                    <p key={line}>{line}</p>
                  ))}
                </div>
                {hints?.length && !draft.trim() && !busy ? (
                  <TypingHints
                    hints={hints}
                    onPick={(text) => {
                      setDraft(text);
                      window.requestAnimationFrame(() => draftRef.current?.focus());
                    }}
                  />
                ) : null}
              </div>
            ) : (
              <p className="pt-10 text-center text-sm leading-7 text-muted">پیام را پایین بنویس.</p>
            )
          ) : (
            messages.map((msg) => {
              const assistantPersona = Boolean(persona) && msg.role === "assistant";
              const wide = Boolean(
                msg.kind === "build" ||
                  msg.campaignId ||
                  msg.compose ||
                  msg.captions ||
                  msg.attachments?.length ||
                  (msg.mediaKind && msg.mediaName),
              );
              const tone =
                msg.kind === "build"
                  ? "ms-auto rounded-2xl border border-line/70 bg-canvas text-warm"
                  : msg.role === "user"
                    ? "ms-0 rounded-2xl bg-accent text-onAccent"
                    : "ms-auto rounded-2xl border border-line/60 bg-paper text-ink";
              const width = assistantPersona && wide ? "min-w-0 flex-1" : wide ? "w-full max-w-[85%]" : "w-fit max-w-[85%]";
              const bubble = (
              <article
                key={assistantPersona ? undefined : msg.id}
                className={cn(
                  "px-3.5 py-2.5 text-sm leading-7",
                  msg.kind === "confirm"
                    ? "w-fit max-w-full rounded-2xl border border-warm/60 bg-canvas text-ink"
                    : cn(width, tone),
                )}
              >
                {assistantPersona ? <p className="mb-1 text-[11px] text-warm">{persona}</p> : null}
                {msg.platformLabel || msg.platform || msg.sender ? (
                  <p className="mb-1 text-[11px] text-warm">
                    {[msg.platformLabel || msg.platform, msg.sender].filter(Boolean).join(" · ")}
                  </p>
                ) : null}
                {msg.text ? <p className="whitespace-pre-wrap">{sanitizeShopText(msg.text, sanitize)}</p> : null}
                {msg.captions && !onPublish ? (
                  <div className="mt-2 space-y-1 text-[11px] leading-6 text-muted">
                    {msg.captions.instagram ? <p className="whitespace-pre-wrap">اینستاگرام: {msg.captions.instagram}</p> : null}
                    {msg.captions.telegram ? <p className="whitespace-pre-wrap">تلگرام: {msg.captions.telegram}</p> : null}
                    {msg.captions.whatsapp ? <p className="whitespace-pre-wrap">واتساپ: {msg.captions.whatsapp}</p> : null}
                  </div>
                ) : null}
                {msg.kind === "confirm" && msg.confirmId && onConfirm ? (
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Button
                      type="button"
                      className="h-auto py-1 text-xs"
                      disabled={busy || confirmId !== msg.confirmId}
                      onClick={() => onConfirm(msg.confirmId || "")}
                    >
                      تأیید
                    </Button>
                    {onCancel ? (
                      <Button
                        type="button"
                        variant="ghost"
                        className="h-auto py-1 text-xs"
                        disabled={busy || confirmId !== msg.confirmId}
                        onClick={() => onCancel(msg.confirmId || "")}
                      >
                        انصراف
                      </Button>
                    ) : null}
                  </div>
                ) : null}
                {msg.kind === "ask" && msg.options?.length ? (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {msg.options.map((option) => (
                      <button
                        key={option}
                        type="button"
                        className="rounded-full border border-warm/40 bg-paper px-3 py-1 text-xs text-ink disabled:opacity-50"
                        disabled={busy}
                        onClick={() => void onSend({ text: option })}
                      >
                        {option}
                      </button>
                    ))}
                  </div>
                ) : null}
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
                {msg.compose?.status === "running" ? <ComposeWait compose={msg.compose} /> : null}
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
              );
              if (!assistantPersona) return bubble;
              return (
                <div key={msg.id} className={cn("ms-auto flex items-end gap-2", wide ? "w-full max-w-[85%]" : "w-fit max-w-[85%]")}>
                  {bubble}
                  <SozanMark className="mb-1 h-8 w-8 shrink-0" glow={false} />
                </div>
              );
            })
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
        {aspects?.length ? (
          <div className="flex items-center gap-2 px-1" role="group" aria-label="نسبت تصویر">
            {aspects.map((row) => {
              const on = aspect === row.id || (!aspect && row.id === "post");
              return (
                <button
                  key={row.id}
                  type="button"
                  onClick={() => setAspect((value) => (value === row.id ? "" : row.id))}
                  className={cn(
                    "min-h-9 rounded-xl px-3 text-xs font-medium",
                    on ? "border border-accent/40 bg-accent/15 text-warm" : "border border-line text-muted",
                  )}
                >
                  {row.label}
                </button>
              );
            })}
          </div>
        ) : null}
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
            ref={draftRef}
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
