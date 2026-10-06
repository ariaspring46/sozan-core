"use client";

import { ReactNode, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown, MessageCircle, SquarePen, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useBackClose } from "@/lib/back-stack";
import { SozanOrb } from "@/components/sozan-orb";

export type ThreadRow = { id: string; title: string; at?: number };

function when(at?: number) {
  if (!at) return "";
  const date = new Date(at * 1000);
  const today = new Date().toDateString() === date.toDateString();
  return today
    ? date.toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit" })
    : date.toLocaleDateString("fa-IR", { day: "numeric", month: "long" });
}

/**
 * سربرگ چت: گوی کوچک سوزان (وقتی فکر می‌کند تند می‌چرخد)، نام، و گفتگوی جاری که با لمس فهرست گفتگوها را
 * در یک برگهٔ پایین‌کش باز می‌کند؛ دکمهٔ گرد «گفتگوی تازه» کنارش.
 */
export function ChatHeader({
  busy,
  threads,
  threadId,
  onOpen,
  onNew,
  extra,
}: {
  /** کنار دکمهٔ «گفتگوی تازه» (مثلاً حلقهٔ پیشرفت راه‌اندازی). */
  extra?: ReactNode;
  busy: boolean;
  threads: ThreadRow[];
  threadId: string;
  onOpen: (id: string) => void;
  onNew: () => void;
}) {
  const [open, setOpen] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);
  const current = threads.find((row) => row.id === threadId);
  useBackClose(open, () => setOpen(false));

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="flex min-w-0 items-center gap-2">
      <h1 className="sr-only">گفتگو با سوزان</h1>
      <button
        type="button"
        className="flex min-h-11 min-w-0 flex-1 items-center gap-2.5 rounded-full py-0.5 pe-2 text-start"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`گفتگوها${current ? `، الان: ${current.title}` : ""}`}
        onClick={() => setOpen(true)}
        disabled={!threads.length}
      >
        <span className="relative shrink-0">
          <SozanOrb size={38} busy={busy} />
          <span aria-hidden className={cn("absolute bottom-0.5 end-0.5 h-2.5 w-2.5 rounded-full ring-2 ring-[rgb(var(--c-chatbg))]", busy ? "bg-warm" : "bg-signal")} />
        </span>
        <span className="min-w-0">
          <span className="block font-sozan text-[17px] font-extrabold leading-6 text-ink">سوزان</span>
          <span className="flex min-w-0 items-center gap-1 text-xs text-muted">
            <span className="truncate">{busy ? "دارد فکر می‌کند…" : current?.title || "دستیار فروش تو"}</span>
            {threads.length ? <ChevronDown size={14} aria-hidden className="shrink-0" /> : null}
          </span>
        </span>
      </button>
      {extra}
      <button
        type="button"
        aria-label="گفتگوی تازه"
        title="گفتگوی تازه"
        className="sozan-glass inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-warm"
        onClick={onNew}
      >
        <SquarePen size={19} aria-hidden="true" />
      </button>
      {open && typeof document !== "undefined"
        ? createPortal(
            <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-start sm:pt-20">
              <button type="button" aria-label="بستن" tabIndex={-1} className="absolute inset-0 cursor-default bg-black/50 backdrop-blur-[2px]" onClick={() => setOpen(false)} />
              <div
                role="dialog"
                aria-modal="true"
                aria-label="گفتگوها"
                className="sozan-chat sozan-sheet relative flex max-h-[75dvh] w-full max-w-md flex-col overflow-hidden rounded-t-[1.75rem] border border-line/50 pb-[max(0.75rem,env(safe-area-inset-bottom))] shadow-card sm:rounded-[1.75rem]"
              >
                <div aria-hidden className="mx-auto mt-2.5 h-1 w-10 rounded-full bg-ink/20 sm:hidden" />
                <div className="flex items-center justify-between px-4 pb-2 pt-3">
                  <p className="font-sozan text-lg font-extrabold text-ink">گفتگوها</p>
                  <button ref={closeRef} type="button" aria-label="بستن فهرست گفتگوها" className="inline-flex h-11 w-11 items-center justify-center rounded-full text-muted" onClick={() => setOpen(false)}>
                    <X size={20} aria-hidden />
                  </button>
                </div>
                <div className="px-3 pb-2">
                  <button
                    type="button"
                    className="sozan-send flex min-h-12 w-full items-center justify-center gap-2 rounded-2xl text-[15px] font-bold"
                    onClick={() => {
                      setOpen(false);
                      onNew();
                    }}
                  >
                    <SquarePen size={18} aria-hidden />
                    گفتگوی تازه
                  </button>
                </div>
                <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto overscroll-contain px-3 pb-2">
                  {threads.map((row) => {
                    const on = row.id === threadId;
                    return (
                      <li key={row.id}>
                        <button
                          type="button"
                          aria-current={on ? "true" : undefined}
                          className={cn("flex min-h-14 w-full items-center gap-3 rounded-2xl px-3 text-start transition", on ? "sozan-glass" : "hover:bg-ink/5")}
                          onClick={() => {
                            setOpen(false);
                            if (!on) onOpen(row.id);
                          }}
                        >
                          <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-xl", on ? "sozan-tile" : "bg-ink/5 text-muted")}>
                            <MessageCircle size={17} aria-hidden />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-[15px] font-medium text-ink">{row.title}</span>
                            {row.at ? <span className="block text-xs text-muted">{when(row.at)}</span> : null}
                          </span>
                          {on ? <Check size={18} aria-hidden className="shrink-0 text-warm" /> : null}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
