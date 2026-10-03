"use client";

import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Mic, Paperclip, SendHorizontal, Square } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ChatAttach } from "@/components/chat-attach";
import { ChatWelcome, type ChatStarter } from "@/components/chat-welcome";
import { useVoiceRecorder, VoiceListening } from "@/components/chat-voice";
import {
  Avatar,
  AvatarSpacer,
  BuildNote,
  ComposeWait,
  ConfirmCard,
  QuickReplies,
  shortWhen,
  TypingBubble,
  useWaitLabel,
  VoteButtons,
} from "@/components/chat-parts";
import { StudioPublishCard, type PublishPayload, type PublishTarget, type StudioAttachment, type StudioCaptions } from "@/components/studio-publish";
import { LinkText } from "@/components/link-text";

export type ChatMsg = {
  id: string;
  role: "user" | "assistant";
  text: string;
  at: number;
  trainId?: string;
  kind?: string;
  /** ابزاری که کارت تأیید برایش آمده (عنوان و نماد کارت از روی آن). */
  tool?: string;
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

const STUDIO_WORDS = /پست|استوری|ریلز|ریل|عکس|تصویر|کمپین|بنر|کپشن/;
const WAIT_LINES = ["دارم فکر می‌کنم…", "یک لحظه…", "جواب را می‌چینم…"];

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
  starters,
  confirmId = "",
  onConfirm,
  onCancel,
  persona = "",
  aspects,
  loading = false,
  banner,
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
  /** کارت‌های شروع در چت خالی؛ لمس، جملهٔ شروع را در کادر می‌گذارد. */
  starters?: readonly ChatStarter[];
  confirmId?: string;
  onConfirm?: (confirmId: string) => void;
  onCancel?: (confirmId: string) => void;
  persona?: string;
  showTime?: boolean;
  /** انتخاب‌گر نسبت خروجی استودیو: پست ۴:۵، مربع، استوری. */
  aspects?: readonly { id: string; label: string; word: string }[];
  /** تا تاریخچه نرسیده، صفحهٔ خوشامد نشان داده نمی‌شود (سوسوی «سلام، من سوزانم» در بازدید دوباره). */
  loading?: boolean;
  /** خطا یا اعلان؛ بالای کادر نوشتن می‌نشیند تا کنار جایی باشد که کاربر دست دارد. */
  banner?: ReactNode;
}) {
  const [draft, setDraft] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const voice = useVoiceRecorder(setFile);
  const [waitLine, setWaitLine] = useState(WAIT_LINES[0]);
  /** کارتی که فروشنده همین حالا لمسش کرد: تا آمدن جواب مدل (چند ثانیه) بسته یا «در حال انجام» می‌ماند؛ اگر درخواست شکست خورد دوباره باز می‌شود. */
  const [tapped, setTapped] = useState<Record<string, "confirm" | "cancel">>({});
  useEffect(() => {
    if (!busy) setTapped({});
  }, [busy]);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const fileRef = useRef<HTMLInputElement>(null);
  const draftRef = useRef<HTMLTextAreaElement>(null);
  const future = tone === "future";
  const waitLabel = useWaitLabel(busy, future ? waitLine : "در حال نوشتن…");
  const canSend = Boolean((draft.trim() || (allowMedia && file)) && !busy);

  const fitDraft = () => {
    const el = draftRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 112)}px`;
  };

  const stickToEnd = () => {
    const el = scrollerRef.current;
    // چت خالی پایین نمی‌رود تا گوی و سلام خوشامد از بالا دیده شوند.
    if (el && stickRef.current && el.querySelector("article")) el.scrollTop = el.scrollHeight;
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
    fitDraft();
  }, [draft]);

  useEffect(() => {
    if (!busy || !future) return;
    let index = 0;
    const timer = window.setInterval(() => {
      index = (index + 1) % WAIT_LINES.length;
      setWaitLine(WAIT_LINES[index]);
    }, 2200);
    return () => window.clearInterval(timer);
  }, [busy, future]);

  const [aspect, setAspect] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSend) return;
    let text = draft.trim();
    const chosen = (aspects || []).find((row) => row.id === aspect);
    if (chosen && chosen.word && !text.includes(chosen.word)) text = `${text} (${chosen.word})`.trim();
    const attached = file || undefined;
    const keepKeyboard = document.activeElement === draftRef.current;
    stickRef.current = true;
    // مثل هر چت دیگر: کادر همان لحظه خالی می‌شود و متن در حباب «در حال ارسال» دیده می‌شود.
    setDraft("");
    setFile(null);
    try {
      await onSend({ text, file: attached });
    } catch {
      // ارسال نشد: متن برمی‌گردد (اگر در این فاصله چیز تازه‌ای نوشته، متن قبلی بالای آن می‌نشیند).
      setDraft((current) => (current.trim() ? `${text}\n${current}` : text));
      setFile((current) => current || attached || null);
    }
    if (keepKeyboard) window.requestAnimationFrame(() => draftRef.current?.focus());
  }

  return (
    <div className="flex h-full flex-col bg-transparent">
      {livePanel}
      <div
        ref={scrollerRef}
        className="sozan-fade-top min-h-0 flex-1 overflow-y-auto"
        onScroll={() => {
          const el = scrollerRef.current;
          if (!el) return;
          stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 96;
        }}
      >
        <div className="sozan-log mx-auto max-w-3xl space-y-3 px-4 pb-8 pt-5" role="log" aria-live="polite" aria-relevant="additions text" aria-label="گفتگو">
          {loading && messages.length === 0 ? (
            <div className="space-y-3 pt-4" aria-hidden="true">
              <div className="h-12 w-3/5 animate-pulse rounded-2xl bg-line/40" />
              <div className="ms-auto h-16 w-4/5 animate-pulse rounded-2xl bg-line/30" />
              <div className="h-10 w-2/5 animate-pulse rounded-2xl bg-line/40" />
            </div>
          ) : messages.length === 0 && !pendingText ? (
            welcome || welcomeLines ? (
              <ChatWelcome
                lines={welcomeLines || SHOP_WELCOME}
                starters={starters}
                onPick={(text) => {
                  setDraft(text);
                  window.requestAnimationFrame(() => draftRef.current?.focus());
                }}
              />
            ) : (
              <p className="pt-10 text-center text-sm leading-7 text-muted">پیام را پایین بنویس.</p>
            )
          ) : (
            messages.map((msg, index) => {
              const prev = messages[index - 1];
              const next = messages[index + 1];
              const assistantPersona = Boolean(persona) && msg.role === "assistant";
              const special = (row?: ChatMsg) => Boolean(row && (row.kind === "confirm" || row.kind === "build"));
              const together = (a?: ChatMsg, b?: ChatMsg) =>
                Boolean(a && b && a.role === b.role && !special(a) && !special(b) && Math.abs((b.at || 0) - (a.at || 0)) < 300);
              const lastInGroup = !together(msg, next);
              const wide = Boolean(
                msg.campaignId || msg.compose || msg.captions || msg.attachments?.length || (msg.mediaKind && msg.mediaName),
              );
              const isLast = index === messages.length - 1;
              const side = msg.role === "user" ? "items-start" : "items-end";

              if (msg.kind === "confirm") {
                return (
                  <div key={msg.id} className={cn("flex flex-col", side)}>
                    <article className="w-full max-w-[92%]">
                      <ConfirmCard
                        tool={msg.tool}
                        text={sanitizeShopText(msg.text, sanitize)}
                        open={Boolean(msg.confirmId && onConfirm && msg.confirmId === confirmId)}
                        busy={busy}
                        tapped={tapped[msg.confirmId || ""]}
                        onConfirm={() => {
                          setTapped((prev) => ({ ...prev, [msg.confirmId || ""]: "confirm" }));
                          onConfirm?.(msg.confirmId || "");
                        }}
                        onCancel={
                          onCancel
                            ? () => {
                                setTapped((prev) => ({ ...prev, [msg.confirmId || ""]: "cancel" }));
                                onCancel(msg.confirmId || "");
                              }
                            : undefined
                        }
                      />
                      {showTime && msg.at ? <p className="mt-1 px-1 text-[11px] text-muted/80">{shortWhen(msg.at)}</p> : null}
                    </article>
                  </div>
                );
              }
              if (msg.kind === "build") {
                return (
                  <div key={msg.id} className={cn("flex flex-col", side)}>
                    <article className="w-full max-w-[92%]">
                      <BuildNote text={msg.text} />
                    </article>
                  </div>
                );
              }

              const bubble = (
                <article
                  className={cn(
                    "px-4 py-2.5 text-[15px] leading-[1.9]",
                    wide ? "w-full max-w-full" : "w-fit max-w-full",
                    msg.role === "user"
                      ? cn("sozan-me rounded-[1.4rem] bg-accentStrong text-onAccent", lastInGroup && "rounded-br-md")
                      : cn("sozan-ai rounded-[1.4rem] text-ink", lastInGroup && "rounded-bl-md", msg.kind === "ask" && "ring-1 ring-accent/35"),
                  )}
                >
                  {msg.platformLabel || msg.platform || msg.sender ? (
                    <p className={cn("mb-1 text-xs", msg.role === "user" ? "text-onAccent/90" : "text-warm")}>
                      {[msg.platformLabel || msg.platform, msg.sender].filter(Boolean).join(" · ")}
                    </p>
                  ) : null}
                  {msg.text ? (
                    <p className="wrap-any whitespace-pre-wrap">
                      {msg.role === "assistant" ? <LinkText text={sanitizeShopText(msg.text, sanitize)} /> : sanitizeShopText(msg.text, sanitize)}
                    </p>
                  ) : null}
                  {msg.captions && !onPublish ? (
                    <div className="wrap-any mt-2 space-y-1 text-xs leading-6 text-muted">
                      {msg.captions.instagram ? <p className="whitespace-pre-wrap">اینستاگرام: {msg.captions.instagram}</p> : null}
                      {msg.captions.telegram ? <p className="whitespace-pre-wrap">تلگرام: {msg.captions.telegram}</p> : null}
                      {msg.captions.whatsapp ? <p className="whitespace-pre-wrap">واتساپ: {msg.captions.whatsapp}</p> : null}
                    </div>
                  ) : null}
                  {msg.kind === "ask" && msg.options?.length && isLast && !busy ? (
                    <QuickReplies options={msg.options} disabled={busy} onPick={(option) => void onSend({ text: option })} />
                  ) : null}
                  {msg.role === "assistant" && msg.trainId ? <VoteButtons trainId={msg.trainId} /> : null}
                  {msg.kind === "draft" ? (
                    <div className="mt-2">
                      <p className="text-xs text-warm">پیش‌نویس هوش مصنوعی — هنوز ارسال نشده</p>
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
                      <p className="text-xs text-danger" role="alert">
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
                      <p className="text-xs text-danger" role="alert">{msg.compose.error || "ساخت تصویر نشد"}</p>
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
                    <Link className="mt-1 inline-flex min-h-11 items-center text-sm font-medium text-warm" href={`/campaigns/${msg.campaignId}`}>
                      باز کردن کمپین
                    </Link>
                  ) : null}
                </article>
              );
              const stamp =
                showTime && msg.at && lastInGroup ? (
                  <p className="mt-1 px-2 text-[11px] text-muted/80">
                    {shortWhen(msg.at)}
                    {msg.status === "sending"
                      ? " · در حال ارسال…"
                      : msg.kind === "outbound" && (msg.status === "sent" || msg.delivered)
                        ? " · ارسال شد"
                        : ""}
                  </p>
                ) : null;
              if (!assistantPersona) {
                return (
                  <div key={msg.id} className={cn("flex flex-col", side)}>
                    <div className={cn("flex min-w-0", wide ? "w-full max-w-[92%]" : "max-w-[86%]")}>{bubble}</div>
                    {stamp}
                  </div>
                );
              }
              return (
                <div key={msg.id} className={cn("flex flex-col", side)}>
                  <div className={cn("flex items-end gap-2", wide ? "w-full max-w-[96%]" : "max-w-[92%]")}>
                    <div className="min-w-0 flex-1">{bubble}</div>
                    {lastInGroup ? <Avatar /> : <AvatarSpacer />}
                  </div>
                  {stamp}
                </div>
              );
            })
          )}
          {pendingText ? (
            <div className="flex flex-col items-start">
              <article className="sozan-me w-fit max-w-[86%] rounded-[1.4rem] rounded-br-md bg-accentStrong px-4 py-2.5 text-[15px] leading-[1.9] text-onAccent opacity-80">
                <p className="wrap-any whitespace-pre-wrap">{pendingText}</p>
              </article>
            </div>
          ) : null}
          {busy ? (
            <div className="flex flex-col items-end">
              <TypingBubble label={waitLabel} />
            </div>
          ) : null}
        </div>
      </div>
      <form className="sozan-dock relative z-10 -mt-6 shrink-0 space-y-2 px-3 pb-2.5 pt-5 [&>*]:mx-auto [&>*]:max-w-3xl" onSubmit={(event) => void submit(event)}>
        {banner}
        {file ? (
          <div className="sozan-glass flex items-center justify-between gap-2 rounded-2xl px-3 text-sm text-muted">
            <span className="truncate">{file.type.startsWith("image/") ? "تصویر" : file.type.startsWith("video/") ? "ویدیو" : "صدا"} · {file.name}</span>
            <button type="button" className="inline-flex min-h-11 shrink-0 items-center px-2 text-warm" onClick={() => setFile(null)}>
              حذف
            </button>
          </div>
        ) : null}
        {voice.recording ? <VoiceListening level={voice.level} /> : null}
        {voice.micError ? <p className="text-sm text-danger" role="alert">{voice.micError}</p> : null}
        {aspects?.length && STUDIO_WORDS.test(draft) ? (
          <div className="flex items-center gap-2 px-1" role="group" aria-label="نسبت تصویر">
            {aspects.map((row) => {
              const on = aspect === row.id || (!aspect && row.id === "post");
              return (
                <button
                  key={row.id}
                  type="button"
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => setAspect((value) => (value === row.id ? "" : row.id))}
                  className={cn(
                    "tap min-h-9 rounded-xl px-3 text-[13px] font-medium",
                    on ? "border border-accent/40 bg-accent/15 text-warm" : "sozan-glass text-muted",
                  )}
                >
                  {row.label}
                </button>
              );
            })}
          </div>
        ) : null}
        <div className="flex items-end gap-2">
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
                className="sozan-glass inline-flex h-[52px] w-[52px] shrink-0 items-center justify-center rounded-full text-ink/80 shadow-card"
                aria-label="پیوست تصویر یا ویدیو"
                disabled={busy}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => fileRef.current?.click()}
              >
                <Paperclip size={20} />
              </button>
            </>
          ) : null}
          <div className="sozan-glass flex min-w-0 flex-1 items-end rounded-[1.65rem] p-[3px] ps-3 shadow-card transition focus-within:border-accent/50 focus-within:ring-4 focus-within:ring-accent/15">
            <textarea
              ref={draftRef}
              className="max-h-28 min-h-11 min-w-0 flex-1 resize-none bg-transparent px-1 py-2.5 text-[16px] leading-6 outline-none"
              rows={1}
              value={draft}
              enterKeyHint="send"
              placeholder={placeholder}
              aria-label={placeholder}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
                // روی گوشی Enter خط تازه است و دکمهٔ «بفرست» می‌فرستد؛ روی کامپیوتر Enter می‌فرستد.
                if (window.matchMedia("(pointer: coarse)").matches) return;
                event.preventDefault();
                if (canSend) event.currentTarget.form?.requestSubmit();
              }}
            />
            <Button
              type="submit"
              aria-label="بفرست"
              className="sozan-send h-11 w-11 shrink-0 rounded-full p-0 transition-transform enabled:active:scale-90"
              disabled={!canSend}
              onMouseDown={(event) => event.preventDefault()}
            >
              <SendHorizontal size={20} className="-scale-x-100" aria-hidden />
            </Button>
          </div>
          {allowMedia ? (
            <button
              type="button"
              className={cn(
                "inline-flex h-[52px] w-[52px] shrink-0 items-center justify-center rounded-full shadow-card",
                voice.recording ? "bg-danger text-onAccent" : "sozan-glass text-ink/80",
              )}
              aria-label={voice.recording ? "پایان ضبط" : "ضبط صدا"}
              disabled={busy}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => void voice.toggle()}
            >
              {voice.recording ? <Square size={17} fill="currentColor" /> : <Mic size={20} />}
            </button>
          ) : null}
        </div>
      </form>
    </div>
  );
}
