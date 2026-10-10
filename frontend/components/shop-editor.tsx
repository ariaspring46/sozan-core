"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  FilePlus2,
  History,
  ImageIcon,
  MousePointerClick,
  Palette,
  SendHorizontal,
  Tag,
  Trash2,
  Type,
  Undo2,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { LinkText } from "@/components/link-text";

export type ShopMsg = { id: string; role: "user" | "assistant"; text: string; at?: number };
export type ShopSelection = {
  text: string;
  tag: string;
  kind?: "image" | "text" | "block";
  src?: string;
  alt?: string;
  /** عکسی که زیر متن یا داخل همین بخش است؛ با نگه داشتن روی نوشتهٔ روی عکس هم عوض‌کردنش ممکن است. */
  image?: { src: string; alt?: string };
  /** `/products/<id>` کارتی که بخش داخل آن است؛ کالای بی‌عکس هم با همین عکس می‌گیرد. */
  product?: string;
};

/** عکس قابل‌عوض‌شدن این انتخاب (خود عکس، یا عکس پشت متن)، یا فقط کارت کالای بی‌عکس. */
export function selectionPhoto(selection: ShopSelection): { src: string; alt?: string } | null {
  if (selection.kind === "image" && selection.src) return { src: selection.src, alt: selection.alt };
  if (selection.image?.src) return selection.image;
  return selection.product ? { src: "", alt: "" } : null;
}

/** سقف متن اشاره‌شده در سرور (`viewTarget` تا ۸۰ نویسه). */
export const TARGET_MAX = 80;

/** همان رنگ‌های نام‌داری که سرور می‌شناسد (`NAMED_COLORS` در ویرایشگر فروشگاه). */
const SWATCHES: { name: string; hex: string }[] = [
  { name: "مسی", hex: "#C45C26" },
  { name: "زرشکی", hex: "#7A1F2B" },
  { name: "طلایی", hex: "#C9A227" },
  { name: "قرمز", hex: "#B42318" },
  { name: "نارنجی", hex: "#EA580C" },
  { name: "زرد", hex: "#EAB308" },
  { name: "سبز", hex: "#15803D" },
  { name: "آبی", hex: "#1D4ED8" },
  { name: "بنفش", hex: "#7C3AED" },
  { name: "صورتی", hex: "#DB2777" },
  { name: "مشکی", hex: "#1A1714" },
];

const PAGES = ["درباره ما", "تماس با ما", "داستان برند", "پرسش‌های متداول"];

type Tool = "" | "colors" | "name" | "cta" | "pages" | "history";

export function selectionLabel(selection: ShopSelection) {
  return selection.kind === "image" ? "عکس" : tagLabel(selection.tag);
}

function tagLabel(tag: string) {
  const t = tag.toLowerCase();
  if (/^h[1-3]$/.test(t)) return "تیتر";
  if (t === "button") return "دکمه";
  if (t === "a") return "لینک";
  if (t === "img" || t === "picture") return "عکس";
  if (t === "p" || t === "span" || t === "li" || /^h[4-6]$/.test(t)) return "متن";
  return "بخش";
}

/** پاسخ سرور را برای فروشنده روان کن: نشانی داخلی نمی‌ماند و دکمه همان «بیلد» نام دارد. */
export function friendlyReply(text: string) {
  return String(text || "")
    .replace(/\s*https?:\/\/(?:localhost|127\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|\d{1,3}(?:\.\d{1,3}){3})(?::\d+)?\S*/g, "")
    .replace(/«?انتشار تغییرات»?/g, "«انتشار»")
    .replace(/«?بیلد»?\s+بزن/g, "«انتشار» را بزن")
    .replace(/«?بیلد»?/g, "«انتشار»");
}

function cleanQuote(text: string) {
  return text.replace(/[«»"]/g, "").replace(/\s+/g, " ").trim();
}

export function ShopEditor({
  brand,
  hidePrices,
  pending,
  busy,
  buildBusy,
  selection,
  messages,
  onRun,
  onPublish,
  onClearSelection,
}: {
  brand: string;
  hidePrices: boolean;
  pending: number;
  busy: boolean;
  buildBusy: boolean;
  selection: ShopSelection | null;
  messages: ShopMsg[];
  /** یک دستور به ویرایشگر زندهٔ فروشگاه؛ `true` یعنی سرور جواب داد. */
  onRun: (text: string, opts?: { target?: string; viewPath?: string }) => Promise<boolean>;
  onPublish: () => void;
  onClearSelection: () => void;
}) {
  const [tool, setTool] = useState<Tool>("");
  const [draft, setDraft] = useState("");
  const [selText, setSelText] = useState("");
  const [nameText, setNameText] = useState(brand);
  const [ctaText, setCtaText] = useState("");
  const draftRef = useRef<HTMLInputElement>(null);
  const locked = busy || buildBusy;

  useEffect(() => {
    setSelText(selection?.text || "");
  }, [selection?.text, selection?.tag]);

  useEffect(() => {
    setNameText(brand);
  }, [brand]);

  const recent = useMemo(
    () => messages.filter((row) => row.text && row.text.trim()).slice(-8),
    [messages],
  );
  const lastReply = [...recent].reverse().find((row) => row.role === "assistant");

  const isImage = selection ? selectionLabel(selection) === "عکس" : false;
  const target = selection && !isImage ? selection.text.slice(0, TARGET_MAX) : "";
  const tooLong = Boolean(selection && selection.text.length > TARGET_MAX);
  const canRewrite = Boolean(target && !tooLong && cleanQuote(selText) && cleanQuote(selText) !== selection?.text);

  async function run(text: string, opts?: { target?: string; viewPath?: string }) {
    if (locked || !text.trim()) return false;
    return onRun(text, opts);
  }

  async function submitDraft(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;
    const keepKeyboard = document.activeElement === draftRef.current;
    const ok = await run(text, target ? { target } : undefined);
    if (ok) setDraft("");
    if (keepKeyboard) window.requestAnimationFrame(() => draftRef.current?.focus());
  }

  function toggle(next: Tool) {
    setTool((value) => (value === next ? "" : next));
  }

  const tools: { id: Tool | "hero" | "prices" | "undo"; label: string; icon: typeof Palette }[] = [
    { id: "colors", label: "رنگ", icon: Palette },
    { id: "name", label: "نام فروشگاه", icon: Type },
    { id: "cta", label: "متن دکمه", icon: MousePointerClick },
    { id: "hero", label: "عکس بالای سایت", icon: ImageIcon },
    { id: "prices", label: hidePrices ? "نمایش قیمت‌ها" : "پنهان کردن قیمت‌ها", icon: Tag },
    { id: "pages", label: "صفحهٔ تازه", icon: FilePlus2 },
    { id: "undo", label: "برگشت", icon: Undo2 },
    { id: "history", label: "گفتگو", icon: History },
  ];

  function onTool(id: (typeof tools)[number]["id"]) {
    if (id === "hero") {
      void run("یک عکس تازه برای بالای سایت بساز");
      return;
    }
    if (id === "prices") {
      void run(hidePrices ? "قیمت‌ها را نشان بده" : "قیمت‌ها را پنهان کن");
      return;
    }
    if (id === "undo") {
      void run("برگرد به حالت قبل");
      return;
    }
    toggle(id);
  }

  return (
    <div className="flex min-h-0 flex-col gap-2 lg:gap-3">
      {pending > 0 ? (
        <div className="flex items-center justify-between gap-2 rounded-2xl border border-accent/30 bg-accent/10 px-3 py-2">
          <p className="min-w-0 text-sm leading-6 text-ink">
            <span className="font-bold">{pending.toLocaleString("fa-IR")} تغییر</span> در پیش‌نمایش است؛ با «انتشار» روی سایت می‌رود.
          </p>
          <Button type="button" className="shrink-0 px-3 text-sm" disabled={buildBusy} onClick={onPublish}>
            انتشار
          </Button>
        </div>
      ) : null}

      {selection ? (
        <section aria-label="بخش انتخاب‌شده" className="rounded-2xl border border-line bg-canvas p-3 shadow-card">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-muted">
              انتخاب‌شده: <span className="font-bold text-warm">{selectionLabel(selection)}</span>
            </p>
            <button type="button" aria-label="لغو انتخاب" className="inline-flex h-11 w-11 items-center justify-center rounded-lg text-muted hover:bg-paper" onClick={onClearSelection}>
              <X size={16} />
            </button>
          </div>
          {isImage ? (
            <p className="mt-1 text-xs leading-6 text-muted">برای عکس بالای سایت دکمهٔ «عکس بالای سایت» را بزن، یا پایین بگو چه عکسی می‌خواهی.</p>
          ) : tooLong ? (
            <p className="mt-1 text-xs leading-6 text-muted">این متن بلند است؛ پایین بنویس چه تغییری بدهم.</p>
          ) : (
            <form
              className="mt-2 space-y-2"
              onSubmit={(event) => {
                event.preventDefault();
                if (!canRewrite) return;
                void run(`بنویس «${cleanQuote(selText)}»`, { target });
              }}
            >
              <label className="sr-only" htmlFor="shop-sel-text">
                متن تازه
              </label>
              <textarea
                id="shop-sel-text"
                rows={2}
                maxLength={TARGET_MAX}
                value={selText}
                readOnly={locked}
                onChange={(event) => setSelText(event.target.value)}
                className="w-full resize-none rounded-xl border border-field bg-paper px-3 py-2 text-[16px] leading-7 text-ink outline-none focus:border-accent"
              />
              <div className="flex gap-2">
                <Button type="submit" className="flex-1 text-sm" disabled={!canRewrite || locked}>
                  ثبت متن
                </Button>
                <button
                  type="button"
                  disabled={locked}
                  onClick={() => void run("این متن را حذف کن", { target })}
                  className="inline-flex min-h-11 items-center gap-1.5 rounded-xl border border-line px-3 text-sm text-danger disabled:opacity-50"
                >
                  <Trash2 size={15} />
                  حذف
                </button>
              </div>
            </form>
          )}
        </section>
      ) : (
        <p className="hidden rounded-2xl border border-dashed border-line px-3 py-2 text-xs leading-6 text-muted lg:block">
          روی هر متن یا دکمه در پیش‌نمایش بزن تا همین‌جا ویرایشش کنی.
        </p>
      )}

      <div role="toolbar" aria-label="ابزارهای ویرایش" className="-mx-1 -my-1 flex snap-x gap-1.5 overflow-x-auto px-1 py-1.5 [mask-image:linear-gradient(to_right,transparent,black_28px)] lg:flex-wrap lg:overflow-visible lg:[mask-image:none]">
        {tools.map((item) => {
          const Icon = item.icon;
          const active = tool === item.id;
          return (
            <button
              key={item.id}
              type="button"
              disabled={locked && !["colors", "name", "cta", "pages", "history"].includes(item.id)}
              aria-pressed={["colors", "name", "cta", "pages", "history"].includes(item.id) ? active : undefined}
              onClick={() => onTool(item.id)}
              className={cn(
                "tap inline-flex min-h-9 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-3 text-[13px] disabled:opacity-50",
                active ? "border-accent bg-accent/15 font-bold text-warm" : "border-line bg-canvas text-ink hover:border-accent/50",
                item.id === "history" && "lg:hidden",
              )}
            >
              <Icon size={14} aria-hidden />
              {item.label}
            </button>
          );
        })}
      </div>

      {tool === "colors" ? (
        <div className="rounded-2xl border border-line bg-canvas p-3">
          <p className="text-xs text-muted">رنگ اصلی سایت (دکمه‌ها و تأکیدها)</p>
          <div className="mt-2 grid grid-cols-6 gap-2 sm:grid-cols-11 lg:grid-cols-6">
            {SWATCHES.map((swatch) => (
              <button
                key={swatch.name}
                type="button"
                disabled={locked}
                title={swatch.name}
                aria-label={`رنگ ${swatch.name}`}
                onClick={() => void run(`رنگ اصلی را ${swatch.name} کن`)}
                className="flex min-h-11 flex-col items-center gap-1 text-xs text-muted disabled:opacity-50"
              >
                <span className="h-9 w-9 rounded-full border border-line shadow-card" style={{ background: swatch.hex }} />
                {swatch.name}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {tool === "name" ? (
        <form
          className="flex gap-2 rounded-2xl border border-line bg-canvas p-3"
          onSubmit={(event) => {
            event.preventDefault();
            const value = cleanQuote(nameText);
            if (!value || value === brand) return;
            void run(`بنویس «${value}»`, { viewPath: "/" });
          }}
        >
          <label className="sr-only" htmlFor="shop-name">
            نام فروشگاه
          </label>
          <input
            id="shop-name"
            value={nameText}
            maxLength={40}
            readOnly={locked}
            onChange={(event) => setNameText(event.target.value)}
            className="min-w-0 flex-1 rounded-xl border border-field bg-paper px-3 text-[16px] text-ink outline-none focus:border-accent"
          />
          <Button type="submit" className="shrink-0 px-4 text-sm" disabled={locked || !cleanQuote(nameText) || cleanQuote(nameText) === brand}>
            ثبت
          </Button>
        </form>
      ) : null}

      {tool === "cta" ? (
        <form
          className="rounded-2xl border border-line bg-canvas p-3"
          onSubmit={(event) => {
            event.preventDefault();
            const value = cleanQuote(ctaText);
            if (!value) return;
            void run(`متن دکمه را عوض کن «${value}»`).then((ok) => ok && setCtaText(""));
          }}
        >
          <p className="text-xs text-muted">متن دکمهٔ اصلی خرید</p>
          <div className="mt-2 flex gap-2">
            <label className="sr-only" htmlFor="shop-cta">
              متن دکمه
            </label>
            <input
              id="shop-cta"
              value={ctaText}
              maxLength={30}
              placeholder="مثلاً همین حالا بخر"
              readOnly={locked}
              onChange={(event) => setCtaText(event.target.value)}
              className="min-w-0 flex-1 rounded-xl border border-field bg-paper px-3 text-[16px] text-ink outline-none focus:border-accent"
            />
            <Button type="submit" className="shrink-0 px-4 text-sm" disabled={locked || !cleanQuote(ctaText)}>
              ثبت
            </Button>
          </div>
        </form>
      ) : null}

      {tool === "pages" ? (
        <div className="rounded-2xl border border-line bg-canvas p-3">
          <p className="text-xs text-muted">یک صفحه بساز و در منوی سایت بگذار</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {PAGES.map((label) => (
              <button
                key={label}
                type="button"
                disabled={locked}
                onClick={() => void run(`صفحهٔ ${label} بساز`)}
                className="min-h-11 rounded-xl border border-line bg-paper px-3 text-sm text-ink hover:border-accent/50 disabled:opacity-50"
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <form onSubmit={(event) => void submitDraft(event)} className="flex items-center gap-2 rounded-2xl border border-field bg-canvas p-1.5 ps-3 focus-within:border-accent">
        {target ? (
          <span className="max-w-[35%] shrink-0 truncate rounded-lg bg-accent/10 px-2 py-1 text-xs text-warm" title={target}>
            «{target}»
          </span>
        ) : null}
        <label className="sr-only" htmlFor="shop-command">
          دستور ویرایش
        </label>
        <input
          ref={draftRef}
          id="shop-command"
          value={draft}
          readOnly={locked}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={target ? "بگو با این چه کنم…" : "بگو چه چیزی در سایت عوض شود…"}
          className="min-h-11 min-w-0 flex-1 bg-transparent text-[16px] text-ink outline-none placeholder:text-muted"
        />
        <Button
          type="submit"
          aria-label="بفرست"
          className="h-11 w-11 shrink-0 p-0"
          disabled={locked || !draft.trim()}
          onMouseDown={(event) => event.preventDefault()}
        >
          <SendHorizontal size={17} className="-scale-x-100" />
        </Button>
      </form>

      <p className="min-h-5 px-1 text-sm leading-6" role="status" aria-live="polite">
        {busy ? (
          <span className="text-warm">در حال اعمال…</span>
        ) : buildBusy ? (
          <span className="text-warm">سایت در حال انتشار است؛ کمی صبر کن.</span>
        ) : lastReply ? (
          <span className="line-clamp-1 text-muted sm:line-clamp-2">
            سوزان: <LinkText text={friendlyReply(lastReply.text)} />
          </span>
        ) : null}
      </p>

      <section
        aria-label="گفتگوی ویرایش"
        className={cn("min-h-0 flex-1 overflow-y-auto rounded-2xl border border-line bg-canvas p-3", tool === "history" ? "block" : "hidden lg:block")}
      >
        <p className="text-xs font-bold text-muted">آخرین تغییرها</p>
        {recent.length ? (
          <ol className="mt-2 space-y-2">
            {recent.map((row) => (
              <li
                key={row.id}
                className={cn(
                  "rounded-xl px-3 py-2 text-sm leading-6",
                  row.role === "user" ? "ms-6 bg-accent/10 text-ink" : "me-6 bg-paper text-ink",
                )}
              >
                {row.role === "assistant" ? <LinkText text={friendlyReply(row.text)} /> : row.text}
              </li>
            ))}
          </ol>
        ) : (
          <p className="mt-2 text-xs leading-6 text-muted">هنوز تغییری نداده‌ای.</p>
        )}
      </section>
    </div>
  );
}
