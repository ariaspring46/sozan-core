"use client";

import { useEffect, useState } from "react";

export const LANDING_SLOGANS = [
  "بگو.\nبساز.\nبفروش.",
  "چت می‌کنی؛\nفروشگاه را می‌بینی.",
  "پست و کپشن\nاز همان چت.",
  "از سؤال مشتری\nتا پرداخت، یک گفتگو.",
] as const;

const INTERVAL_MS = 4200;

export function LandingSloganRotator() {
  const [index, setIndex] = useState(0);
  const [reduce, setReduce] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setReduce(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  useEffect(() => {
    if (reduce) return;
    const timer = window.setInterval(() => {
      setIndex((n) => (n + 1) % LANDING_SLOGANS.length);
    }, INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [reduce]);

  const text = LANDING_SLOGANS[reduce ? 0 : index];
  return (
    <h1
      className="landing-fade landing-fade-title landing-display min-h-[3.54em] text-[clamp(2.5rem,6.4vw,5.2rem)] leading-[1.18]"
      aria-live="polite"
    >
      <span key={text} className="landing-slogan sozan-title-glow whitespace-pre-line">
        {text}
      </span>
    </h1>
  );
}
