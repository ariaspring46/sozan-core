"use client";

import { FormEvent, ReactNode, Ref, useEffect, useImperativeHandle, useRef, useState } from "react";
import { ChevronDown, ImagePlus, Mic, SendHorizontal, Square, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useVoiceRecorder, VoiceListening } from "@/components/chat-voice";

export type ChatSend = { text: string; file?: File };
export type ComposerHandle = { fill: (text: string) => void };
export type Aspect = { id: string; label: string; word: string };

const STUDIO_WORDS = /پست|استوری|ریلز|ریل|عکس|تصویر|کمپین|بنر|کپشن/;

function vibrate() {
  try {
    navigator.vibrate?.(8);
  } catch {
    /* بعضی مرورگرها اجازه نمی‌دهند */
  }
}

/**
 * نوار نوشتن شناور چت (سبک پیام‌رسان‌ها): کپسول شیشه‌ای با دکمهٔ پیوست داخلش، و یک دکمهٔ گرد که
 * تا چیزی ننوشته‌ای میکروفون است و با اولین حرف «بفرست» می‌شود. متنِ ارسال‌نشده (خطای شبکه) به کادر برمی‌گردد.
 */
export function ChatComposer({
  handle,
  busy,
  placeholder,
  allowMedia,
  aspects,
  banner,
  away,
  onJump,
  onSend,
  onTyping,
}: {
  handle?: Ref<ComposerHandle>;
  busy: boolean;
  placeholder: string;
  allowMedia: boolean;
  aspects?: readonly Aspect[];
  banner?: ReactNode;
  /** کاربر بالاتر از آخرین پیام است: دکمهٔ «برو به آخرین پیام» دیده شود. */
  away?: boolean;
  onJump?: () => void;
  /** اگر ارسال نشد خطا می‌دهد تا متن برگردد. */
  onSend: (payload: ChatSend) => Promise<void> | void;
  onTyping?: (typing: boolean) => void;
}) {
  const [draft, setDraft] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [aspect, setAspect] = useState("");
  const voice = useVoiceRecorder(setFile);
  const fileRef = useRef<HTMLInputElement>(null);
  const draftRef = useRef<HTMLTextAreaElement>(null);
  const typed = Boolean(draft.trim());
  const canSend = Boolean((typed || (allowMedia && file)) && !busy);
  const showMic = allowMedia && !typed && !file;

  useImperativeHandle(handle, () => ({
    fill: (text: string) => {
      setDraft(text);
      window.requestAnimationFrame(() => {
        const el = draftRef.current;
        el?.focus();
        el?.setSelectionRange(text.length, text.length);
      });
    },
  }));

  useEffect(() => {
    const el = draftRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 112)}px`;
  }, [draft]);

  useEffect(() => {
    onTyping?.(typed);
  }, [typed, onTyping]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSend) return;
    let text = draft.trim();
    const chosen = (aspects || []).find((row) => row.id === aspect);
    if (chosen && chosen.word && !text.includes(chosen.word)) text = `${text} (${chosen.word})`.trim();
    const attached = file || undefined;
    const keepKeyboard = document.activeElement === draftRef.current;
    vibrate();
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
    <form className="sozan-dock relative z-10 -mt-6 shrink-0 space-y-2 px-3 pb-2.5 pt-5 [&>*]:mx-auto [&>*]:max-w-3xl" onSubmit={(event) => void submit(event)}>
      {banner}
      {file ? (
        <div className="sozan-glass sozan-rise flex items-center justify-between gap-2 rounded-2xl ps-3 text-sm text-ink">
          <span className="flex min-w-0 items-center gap-2">
            <span className="sozan-tile flex h-8 w-8 shrink-0 items-center justify-center rounded-xl">
              {file.type.startsWith("audio/") ? <Mic size={15} aria-hidden /> : <ImagePlus size={15} aria-hidden />}
            </span>
            <span className="truncate">
              {file.type.startsWith("image/") ? "تصویر" : file.type.startsWith("video/") ? "ویدیو" : "صدا"} · {file.name}
            </span>
          </span>
          <button type="button" aria-label="حذف پیوست" className="inline-flex h-11 w-11 shrink-0 items-center justify-center text-muted" onClick={() => setFile(null)}>
            <X size={18} aria-hidden />
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
                className={cn("tap min-h-9 rounded-full px-3.5 text-[13px] font-medium transition", on ? "sozan-tile" : "sozan-glass text-muted")}
              >
                {row.label}
              </button>
            );
          })}
        </div>
      ) : null}
      <div className="flex items-end gap-2">
        <div className="sozan-glass flex min-w-0 flex-1 items-end rounded-[1.65rem] p-[3px] shadow-card transition focus-within:border-accent/50 focus-within:ring-4 focus-within:ring-accent/15">
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
                className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-muted transition hover:text-warm"
                aria-label="پیوست تصویر یا ویدیو"
                disabled={busy}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => fileRef.current?.click()}
              >
                <ImagePlus size={21} aria-hidden />
              </button>
            </>
          ) : null}
          <textarea
            ref={draftRef}
            className={cn("max-h-28 min-h-11 min-w-0 flex-1 resize-none bg-transparent py-2.5 text-[16px] leading-6 outline-none", allowMedia ? "pe-3" : "px-3")}
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
        </div>
        {voice.recording ? (
          <button
            type="button"
            aria-label="پایان ضبط"
            className="sozan-rise inline-flex h-[52px] w-[52px] shrink-0 items-center justify-center rounded-full bg-danger text-canvas shadow-card"
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => void voice.toggle()}
          >
            <Square size={17} fill="currentColor" aria-hidden />
          </button>
        ) : showMic ? (
          <button
            type="button"
            aria-label="ضبط صدا"
            className="sozan-send inline-flex h-[52px] w-[52px] shrink-0 items-center justify-center rounded-full shadow-card transition-transform active:scale-90"
            disabled={busy}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => void voice.toggle()}
          >
            <Mic size={21} aria-hidden />
          </button>
        ) : (
          <button
            type="submit"
            aria-label="بفرست"
            className="sozan-send sozan-pop inline-flex h-[52px] w-[52px] shrink-0 items-center justify-center rounded-full shadow-card transition-transform active:scale-90 disabled:text-muted"
            disabled={!canSend}
            onMouseDown={(event) => event.preventDefault()}
          >
            <SendHorizontal size={21} className="-scale-x-100" aria-hidden />
          </button>
        )}
      </div>
      {away && onJump ? (
        <button
          type="button"
          aria-label="رفتن به آخرین پیام"
          onClick={onJump}
          className="sozan-glass sozan-rise absolute -top-10 left-1/2 inline-flex h-11 w-11 -translate-x-1/2 items-center justify-center rounded-full text-ink shadow-card"
        >
          <ChevronDown size={20} aria-hidden />
        </button>
      ) : null}
    </form>
  );
}
