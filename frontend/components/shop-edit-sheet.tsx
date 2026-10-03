"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { ImagePlus, Sparkles, SendHorizontal, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LinkText } from "@/components/link-text";
import { friendlyReply, selectionLabel, TARGET_MAX, type ShopSelection } from "@/components/shop-editor";

function cleanQuote(text: string) {
  return text.replace(/[«»"]/g, "").replace(/\s+/g, " ").trim();
}

/** نشانی عکس انتخاب‌شده اگر از همان فروشگاه است؛ برای پیش‌نمایش کوچک در برگه. */
function thumbSrc(selection: ShopSelection, href: string) {
  if (!selection.src) return "";
  try {
    const base = new URL(href);
    const url = new URL(selection.src, base);
    if ((url.protocol === "http:" || url.protocol === "https:") && url.host === base.host) return url.href;
  } catch {
    /* ignore */
  }
  return "";
}

/**
 * برگهٔ پایین موبایل: بعد از نگه داشتن انگشت روی یک بخش سایت باز می‌شود. فقط همین بخش را ویرایش می‌کند:
 * دستور آزاد، متن تازه، یا عکس از گوشی. چت جداگانه‌ای در صفحه نیست.
 */
export function ShopEditSheet({
  selection,
  href,
  busy,
  locked,
  reply,
  error,
  onRun,
  onImage,
  onClose,
}: {
  selection: ShopSelection;
  href: string;
  busy: boolean;
  /** بیلد در جریان است: ویرایش تا پایانش ممکن نیست. */
  locked: boolean;
  reply: string;
  error: string;
  onRun: (text: string, opts?: { target?: string }) => Promise<boolean>;
  onImage: (file: File) => Promise<boolean>;
  onClose: () => void;
}) {
  const isImage = selection.kind === "image";
  const isHero = isImage && /hero/i.test(selection.src || "");
  const target = !isImage ? selection.text.slice(0, TARGET_MAX) : "";
  const tooLong = !isImage && selection.text.length > TARGET_MAX;
  const [draft, setDraft] = useState("");
  const [selText, setSelText] = useState(selection.text);
  const fileRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const disabled = busy || locked;
  const thumb = isImage ? thumbSrc(selection, href) : "";

  useEffect(() => {
    setSelText(selection.text);
    setDraft("");
  }, [selection]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const canRewrite = Boolean(target && !tooLong && cleanQuote(selText) && cleanQuote(selText) !== selection.text);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || disabled) return;
    const keep = document.activeElement === inputRef.current;
    const ok = await onRun(text, target ? { target } : undefined);
    if (ok) setDraft("");
    if (keep) window.requestAnimationFrame(() => inputRef.current?.focus());
  }

  return (
    <section
      role="dialog"
      aria-label="ویرایش این بخش"
      className="absolute inset-x-0 bottom-0 z-30 flex max-h-[78%] flex-col gap-3 overflow-y-auto overscroll-contain rounded-t-3xl border border-b-0 border-line bg-paper px-4 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2 shadow-card"
    >
      <div className="mx-auto h-1 w-10 shrink-0 rounded-full bg-line" aria-hidden />
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-3">
          {thumb ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={thumb} alt="" referrerPolicy="no-referrer" className="h-12 w-12 shrink-0 rounded-lg border border-line object-cover" />
          ) : null}
          <div className="min-w-0">
            <p className="text-xs text-muted">
              انتخاب‌شده: <span className="font-bold text-warm">{selectionLabel(selection)}</span>
            </p>
            {!isImage && selection.text ? (
              <p dir="auto" className="line-clamp-2 text-sm leading-6 text-ink">
                «{selection.text}»
              </p>
            ) : null}
            {isImage && selection.alt ? <p dir="auto" className="line-clamp-1 text-sm text-ink">{selection.alt}</p> : null}
          </div>
        </div>
        <button
          type="button"
          aria-label="بستن"
          className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-muted hover:bg-canvas"
          onClick={onClose}
        >
          <X size={20} aria-hidden />
        </button>
      </div>

      {isImage ? (
        <div className="flex flex-wrap gap-2">
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            className="sr-only"
            tabIndex={-1}
            aria-label="عکس تازه"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) void onImage(file);
            }}
          />
          <Button type="button" className="flex-1 gap-2" disabled={disabled} onClick={() => fileRef.current?.click()}>
            <ImagePlus size={17} aria-hidden />
            عکس از گوشی
          </Button>
          {isHero ? (
            <Button
              type="button"
              variant="ghost"
              className="flex-1 gap-2"
              disabled={disabled}
              onClick={() => void onRun(draft.trim() ? `یک عکس تازه برای بالای سایت بساز: ${draft.trim()}` : "یک عکس تازه برای بالای سایت بساز")}
            >
              <Sparkles size={17} aria-hidden />
              با هوش مصنوعی بساز
            </Button>
          ) : null}
        </div>
      ) : target && !tooLong ? (
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (canRewrite && !disabled) void onRun(`بنویس «${cleanQuote(selText)}»`, { target });
          }}
        >
          <label className="sr-only" htmlFor="shop-sheet-text">
            متن تازه
          </label>
          <textarea
            id="shop-sheet-text"
            rows={2}
            maxLength={TARGET_MAX}
            value={selText}
            readOnly={disabled}
            onChange={(event) => setSelText(event.target.value)}
            className="w-full resize-none rounded-xl border border-field bg-canvas px-3 py-2 text-[16px] leading-7 text-ink outline-none focus:border-accent"
          />
          <div className="flex gap-2">
            <Button type="submit" className="flex-1 text-sm" disabled={!canRewrite || disabled}>
              ثبت متن
            </Button>
            <button
              type="button"
              disabled={disabled}
              onClick={() => void onRun("این متن را حذف کن", { target })}
              className="inline-flex min-h-11 items-center gap-1.5 rounded-xl border border-line px-3 text-sm text-danger disabled:opacity-50"
            >
              <Trash2 size={15} aria-hidden />
              حذف
            </button>
          </div>
        </form>
      ) : tooLong ? (
        <p className="text-xs leading-6 text-muted">این بخش بلند است؛ پایین بنویس چه تغییری بدهم.</p>
      ) : null}

      <form onSubmit={(event) => void submit(event)} className="flex items-center gap-2 rounded-2xl border border-field bg-canvas p-1.5 ps-3 focus-within:border-accent">
        <label className="sr-only" htmlFor="shop-sheet-command">
          دستور برای این بخش
        </label>
        <input
          ref={inputRef}
          id="shop-sheet-command"
          value={draft}
          readOnly={disabled}
          enterKeyHint="send"
          onChange={(event) => setDraft(event.target.value)}
          placeholder={isImage ? "بگو با این عکس چه کنم…" : "بگو با این بخش چه کنم…"}
          className="min-h-11 min-w-0 flex-1 bg-transparent text-[16px] text-ink outline-none placeholder:text-muted"
        />
        <Button
          type="submit"
          aria-label="بفرست"
          className="h-11 w-11 shrink-0 p-0"
          disabled={disabled || !draft.trim()}
          onMouseDown={(event) => event.preventDefault()}
        >
          <SendHorizontal size={17} className="-scale-x-100" />
        </Button>
      </form>

      <p className="min-h-6 text-sm leading-7" role="status" aria-live="polite">
        {busy ? (
          <span className="text-warm">در حال اعمال…</span>
        ) : locked ? (
          <span className="text-warm">سایت در حال بیلد است؛ کمی صبر کن.</span>
        ) : error ? (
          <span className="text-danger" role="alert">
            {error}
          </span>
        ) : reply ? (
          <span className="text-ink">
            <LinkText text={friendlyReply(reply)} />
          </span>
        ) : null}
      </p>
    </section>
  );
}
