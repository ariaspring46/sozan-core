"use client";

import { ReactNode, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ChatAttach } from "@/components/chat-attach";
import { ChatWelcome, type ChatStarter } from "@/components/chat-welcome";
import { ChatComposer, type Aspect, type ChatSend, type ComposerHandle } from "@/components/chat-composer";
import {
  Avatar,
  AvatarSpacer,
  BuildNote,
  ComposeWait,
  ConfirmCard,
  PendingDock,
  QuickReplies,
  RevealText,
  shortWhen,
  TypingBubble,
  useFreshIds,
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

export type { ChatSend };

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

export function ChatThread({
  messages,
  busy,
  placeholder,
  onSend,
  pendingText,
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
  pendingText?: string;
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
  aspects?: readonly Aspect[];
  /** تا تاریخچه نرسیده، صفحهٔ خوشامد نشان داده نمی‌شود (سوسوی «سلام، من سوزانم» در بازدید دوباره). */
  loading?: boolean;
  /** خطا یا اعلان؛ بالای کادر نوشتن می‌نشیند تا کنار جایی باشد که کاربر دست دارد. */
  banner?: ReactNode;
}) {
  const composer = useRef<ComposerHandle>(null);
  const [typing, setTyping] = useState(false);
  const [away, setAway] = useState(false);
  /** کارتی که فروشنده همین حالا لمسش کرد: تا آمدن جواب مدل (چند ثانیه) بسته یا «در حال انجام» می‌ماند؛ اگر درخواست شکست خورد دوباره باز می‌شود. */
  const [tapped, setTapped] = useState<Record<string, "confirm" | "cancel">>({});
  useEffect(() => {
    if (!busy) setTapped({});
  }, [busy]);
  const tap = (id: string, how: "confirm" | "cancel") => {
    setTapped((prev) => ({ ...prev, [id]: how }));
    (how === "confirm" ? onConfirm : onCancel)?.(id);
  };
  const scrollerRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  /** آخرین جایی که خود برنامه گفتگو را به آن برد؛ رویداد scroll در همان‌جا کار کاربر نیست. */
  const autoTop = useRef(-1);
  const waitLabel = useWaitLabel(busy, "دارم فکر می‌کنم…");
  const fresh = useFreshIds(
    messages.map((msg) => msg.id),
    Boolean(persona) && !loading,
  );

  const stickToEnd = useCallback(() => {
    const el = scrollerRef.current;
    // چت خالی پایین نمی‌رود تا گوی و سلام خوشامد از بالا دیده شوند.
    if (!el || !stickRef.current || !el.querySelector("article")) return;
    el.scrollTop = el.scrollHeight;
    autoTop.current = el.scrollTop;
  }, []);

  // پیش از نقاشی: رویداد scroll مرورگر (جابه‌جایی محتوا) نباید «دنبال کردن گفتگو» را خاموش کند.
  useLayoutEffect(() => {
    stickToEnd();
  }, [messages, busy, pendingText, stickToEnd]);

  // بزرگ و کوچک شدن محتوا یا قاب (اعلان، پیوست، کیبورد) گفتگو را پایین نگه می‌دارد.
  useEffect(() => {
    const el = scrollerRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const watch = new ResizeObserver(stickToEnd);
    watch.observe(el);
    if (el.firstElementChild) watch.observe(el.firstElementChild);
    return () => watch.disconnect();
  }, [stickToEnd]);

  return (
    <div className="flex h-full flex-col bg-transparent">
      <div
        ref={scrollerRef}
        className="sozan-fade-top min-h-0 flex-1 overflow-y-auto"
        onScroll={() => {
          const el = scrollerRef.current;
          if (!el || Math.abs(el.scrollTop - autoTop.current) < 2) return;
          stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 96;
          setAway(!stickRef.current);
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
              <ChatWelcome lines={welcomeLines || SHOP_WELCOME} starters={starters} excited={typing} onPick={(text) => composer.current?.fill(text)} />
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
                  <div key={msg.id} data-confirm={msg.confirmId} className={cn("flex flex-col", side)}>
                    <article className="w-full max-w-[92%]">
                      <ConfirmCard
                        tool={msg.tool}
                        text={sanitizeShopText(msg.text, sanitize)}
                        open={Boolean(msg.confirmId && onConfirm && msg.confirmId === confirmId)}
                        busy={busy}
                        tapped={tapped[msg.confirmId || ""]}
                        onConfirm={() => tap(msg.confirmId || "", "confirm")}
                        onCancel={onCancel ? () => tap(msg.confirmId || "", "cancel") : undefined}
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
                    <RevealText className="wrap-any whitespace-pre-wrap" on={msg.role === "assistant" && fresh.has(msg.id)}>
                      {msg.role === "assistant" ? <LinkText text={sanitizeShopText(msg.text, sanitize)} /> : sanitizeShopText(msg.text, sanitize)}
                    </RevealText>
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
                              composer.current?.fill(msg.text);
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
      <ChatComposer
        handle={composer}
        busy={busy}
        placeholder={placeholder}
        allowMedia={allowMedia}
        aspects={aspects}
        banner={
          <>
            {confirmId && onConfirm ? (
              <PendingDock
                cardId={confirmId}
                tool={messages.findLast((row) => row.confirmId === confirmId)?.tool}
                busy={busy}
                tapped={tapped[confirmId]}
                scroller={scrollerRef}
                version={messages.length}
                onConfirm={() => tap(confirmId, "confirm")}
                onCancel={onCancel ? () => tap(confirmId, "cancel") : undefined}
              />
            ) : null}
            {banner}
          </>
        }
        away={away && messages.length > 0}
        onJump={() => {
          stickRef.current = true;
          setAway(false);
          scrollerRef.current?.scrollTo({ top: scrollerRef.current.scrollHeight, behavior: "smooth" });
        }}
        onSend={(payload) => {
          stickRef.current = true;
          return onSend(payload);
        }}
        onTyping={setTyping}
      />
    </div>
  );
}
