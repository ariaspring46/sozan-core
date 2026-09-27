"use client";

import { useEffect, useMemo, useState } from "react";

type Phase = "type" | "hold" | "wind" | "gap";

const TYPE_MS = 55;
const HOLD_MS = 1500;
const WIND_MS = 900;
const WIND_STAGGER_MS = 70;
const GAP_MS = 1000;

function reducedMotion() {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

/**
 * جمله‌های راهنما در پس‌زمینهٔ چت خالی: تایپ می‌شوند، باد کلمه‌ها را می‌برد،
 * یک ثانیه مکث و جملهٔ بعدی. زدن روی جمله آن را در کادر نوشتن می‌گذارد.
 */
export function TypingHints({ hints, onPick }: { hints: string[]; onPick?: (text: string) => void }) {
  const [index, setIndex] = useState(0);
  const [count, setCount] = useState(0);
  const [phase, setPhase] = useState<Phase>("type");
  const [still, setStill] = useState(false);

  const text = hints.length ? hints[index % hints.length] : "";
  const chars = useMemo(() => Array.from(text), [text]);
  const words = useMemo(() => text.split(" ").filter(Boolean), [text]);

  useEffect(() => {
    setStill(reducedMotion());
  }, []);

  useEffect(() => {
    if (!text) return;
    let timer = 0;
    if (phase === "type") {
      if (still) {
        setCount(chars.length);
        setPhase("hold");
        return;
      }
      if (count < chars.length) {
        // کمی نامنظم تا حس تایپ واقعی بدهد
        timer = window.setTimeout(() => setCount((value) => value + 1), TYPE_MS + Math.random() * 40);
      } else {
        setPhase("hold");
      }
    } else if (phase === "hold") {
      timer = window.setTimeout(() => setPhase("wind"), still ? HOLD_MS * 2 : HOLD_MS);
    } else if (phase === "wind") {
      timer = window.setTimeout(() => setPhase("gap"), still ? 400 : WIND_MS + words.length * WIND_STAGGER_MS);
    } else {
      timer = window.setTimeout(() => {
        setIndex((value) => (value + 1) % hints.length);
        setCount(0);
        setPhase("type");
      }, GAP_MS);
    }
    return () => window.clearTimeout(timer);
  }, [phase, count, chars.length, words.length, hints.length, still, text]);

  if (!text) return null;

  const typed = phase === "type" || phase === "hold";

  return (
    <div className="flex min-h-[5.5rem] flex-col items-center justify-center px-2 text-center">
      <button
        type="button"
        className="max-w-md text-lg font-medium leading-9 text-ink/70 outline-none transition-colors hover:text-ink focus-visible:text-ink sm:text-xl"
        aria-label={`نمونه: ${text}. برای نوشتنش در کادر بزن`}
        onClick={() => onPick?.(text)}
        disabled={phase === "gap"}
      >
        {typed ? (
          <span aria-hidden>
            «{chars.slice(0, count).join("")}
            {count >= chars.length ? "»" : null}
            <span className="sozan-caret ms-0.5 inline-block h-6 w-0.5 translate-y-1 rounded-full bg-warm" />
          </span>
        ) : phase === "wind" ? (
          <span aria-hidden className={still ? "sozan-wind-still" : undefined}>
            {words.map((word, i) => (
              <span key={`${index}-${i}`}>
                <span
                  className={still ? "inline-block" : "sozan-wind inline-block"}
                  style={still ? undefined : { animationDelay: `${i * WIND_STAGGER_MS}ms`, animationDuration: `${WIND_MS}ms` }}
                >
                  {i === 0 ? "«" : ""}
                  {word}
                  {i === words.length - 1 ? "»" : ""}
                </span>{" "}
              </span>
            ))}
          </span>
        ) : (
          <span aria-hidden>&nbsp;</span>
        )}
      </button>
      <p className="mt-1 text-[11px] text-muted">مثلاً این را بنویس — یا روی جمله بزن</p>
    </div>
  );
}
