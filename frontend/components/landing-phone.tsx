"use client";

import { useEffect, useState } from "react";
import { Check, Hammer, Mic, SendHorizontal, Store } from "lucide-react";
import { cn } from "@/lib/utils";
import { SozanOrb } from "@/components/sozan-orb";
import { RevealText } from "@/components/chat-parts";

const ASK = "یه فروشگاه لباس بساز؛ تیره و مینیمال";
const REPLY = "حسش را گرفتم: زمینهٔ مشکی، جزئیات مسی و عکس‌های بزرگ. با کالاهای انبارت بسازم؟";
const PRODUCTS = [
  { name: "پیراهن کتان", price: "۸۹۰" },
  { name: "کیف چرمی", price: "۱٬۲۵۰" },
  { name: "شال پشمی", price: "۴۲۰" },
  { name: "کلاه بافت", price: "۳۲۰" },
];

/** زمان هر صحنه (میلی‌ثانیه از شروع): نوشتن، ارسال، فکر کردن، جواب، «بساز»، ساخت، آماده. */
const STAGES = [0, 900, 2900, 3300, 4800, 7300, 7900, 10600, 14800];
const LAST = STAGES.length - 2;

function useStage() {
  const [stage, setStage] = useState(0);
  const [typed, setTyped] = useState(0);
  const [still, setStill] = useState(false);
  useEffect(() => {
    try {
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        setStill(true);
        setStage(LAST);
        return;
      }
    } catch {
      /* مرورگر قدیمی */
    }
    let timers: number[] = [];
    const run = () => {
      setStage(0);
      setTyped(0);
      timers = STAGES.map((at, index) =>
        window.setTimeout(() => {
          if (index === STAGES.length - 1) run();
          else setStage(index);
        }, at),
      );
    };
    run();
    return () => timers.forEach((id) => window.clearTimeout(id));
  }, []);
  useEffect(() => {
    if (stage !== 1) return;
    const timer = window.setInterval(() => setTyped((n) => Math.min(ASK.length, n + 1)), 50);
    return () => window.clearInterval(timer);
  }, [stage]);
  return { stage, typed: stage === 1 ? ASK.slice(0, typed) : "", still };
}

/** دموی زندهٔ چت سوزان در قاب گوشی (فقط نمایشی، برای صفحه‌خوان پنهان). */
export function LandingPhone() {
  const { stage, typed, still } = useStage();
  const thinking = stage === 3 || stage === 6;
  return (
    <div className="relative mx-auto w-[min(19.5rem,84vw)]" aria-hidden>
      <span className="sozan-halo pointer-events-none absolute -inset-16 rounded-full opacity-80" />
      <div className="landing-phone relative">
        <div className="landing-phone-screen sozan-chat flex h-[36rem] flex-col">
          <div className="flex items-center gap-2.5 px-4 pb-2 pt-4">
            <span className="relative">
              <SozanOrb size={32} busy={thinking} />
              <span className={cn("absolute bottom-0 end-0 h-2 w-2 rounded-full ring-2 ring-[rgb(var(--c-chatbg))]", thinking ? "bg-warm" : "bg-signal")} />
            </span>
            <span>
              <span className="block font-sozan text-[14px] font-extrabold leading-5 text-ink">سوزان</span>
              <span className="block text-[10.5px] text-muted">{thinking ? "دارد فکر می‌کند…" : "دستیار فروش تو"}</span>
            </span>
          </div>

          <div className="sozan-fade-top flex min-h-0 flex-1 flex-col justify-end gap-2.5 overflow-hidden px-3 pb-3 text-[12.5px] leading-[1.85]">
            {stage < 2 ? (
              <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
                <div className="relative grid place-items-center">
                  <span className="sozan-halo absolute -inset-6 rounded-full" />
                  <SozanOrb size={96} busy={stage === 1} className="relative" />
                </div>
                <p className="sozan-title-glow font-sozan text-xl font-extrabold">عصر بخیر، مینا</p>
                <p className="px-6 text-[11.5px] leading-6 text-muted">بگو امروز چه کاری برایت بکنم.</p>
              </div>
            ) : null}
            {stage >= 2 ? <p className="sozan-me sozan-rise ms-0 me-auto max-w-[85%] self-start rounded-2xl rounded-br-md px-3 py-1.5 text-onAccent">{ASK}</p> : null}
            {stage === 3 ? (
              <div className="sozan-rise flex items-center gap-2 self-end">
                <span className="sozan-ai rounded-full px-3 py-1.5">
                  <span className="sozan-shine text-[11.5px] font-medium">دارم فکر می‌کنم…</span>
                </span>
                <SozanOrb size={30} busy />
              </div>
            ) : null}
            {stage >= 4 ? (
              <div className="sozan-ai sozan-rise max-w-[88%] self-end rounded-2xl rounded-bl-md px-3 py-2 text-ink">
                <RevealText on={!still}>{REPLY}</RevealText>
                {stage === 4 || stage === 5 ? (
                  <div className="mt-2 flex flex-wrap gap-1.5" role="group">
                    {["بساز", "رنگ‌ها را نشان بده"].map((label) => (
                      <span
                        key={label}
                        className={cn(
                          "rounded-full border px-3 py-1 text-[11px] font-medium transition",
                          stage === 5 && label === "بساز" ? "scale-95 border-accent bg-accent/40 text-onAccent" : "border-accent/45 bg-accent/10",
                        )}
                      >
                        {label}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
            {stage >= 6 ? <p className="sozan-me sozan-rise max-w-[60%] self-start rounded-2xl rounded-br-md px-3 py-1.5 text-onAccent">بساز</p> : null}
            {stage >= 6 ? (
              <div className="sozan-card sozan-rise w-[92%] self-end overflow-hidden rounded-2xl">
                <div className="flex items-center gap-2.5 px-3 py-2.5">
                  <span className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-xl", stage >= 7 ? "bg-signal/20 text-signal" : "sozan-tile")}>
                    {stage >= 7 ? <Check size={15} /> : <Hammer size={15} className="sozan-hammer" />}
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[10px] text-warm">{stage >= 7 ? "فروشگاه" : "در حال ساخت"}</span>
                    <span className="block text-[12px] font-bold text-ink">{stage >= 7 ? "فروشگاهت آماده شد" : "طراحی صفحه و چیدن کالاها…"}</span>
                  </span>
                </div>
                <div className="mx-3 h-1 overflow-hidden rounded-full bg-line/50">
                  <div className="landing-progress h-full rounded-full" />
                </div>
                {stage >= 7 ? (
                  <div className="sozan-rise m-3 overflow-hidden rounded-xl border border-ink/10 bg-[rgb(var(--c-chatbg))]">
                    <div className="flex items-center justify-between border-b border-ink/10 px-2.5 py-1.5">
                      <span className="flex items-center gap-1 text-[10px] font-bold text-ink">
                        <Store size={11} className="text-warm" />
                        مینا
                      </span>
                      <span className="text-[9px] text-muted" dir="ltr">
                        mina.sozan-core.ir
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-1.5 p-2">
                      {PRODUCTS.map((item) => (
                        <div key={item.name} className="rounded-lg bg-ink/5 p-1">
                          <div className="landing-swatch h-10 rounded-md" />
                          <p className="mt-1 truncate text-[9px] text-ink/80">{item.name}</p>
                          <p className="text-[9px] text-warm">{item.price} هزار</p>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="h-3" />
                )}
              </div>
            ) : null}
          </div>

          <div className="flex items-end gap-1.5 px-3 pb-4">
            <div className="sozan-glass flex min-h-10 flex-1 items-center rounded-full px-3.5 text-[11.5px]">
              {typed ? <span className="text-ink">{typed}</span> : <span className="text-muted">به سوزان بگو…</span>}
              {stage === 1 ? <span className="sozan-caret ms-0.5 inline-block h-3.5 w-px bg-warm" /> : null}
            </div>
            <span className="sozan-send flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accentStrong text-onAccent">
              {typed ? <SendHorizontal size={16} className="-scale-x-100" /> : <Mic size={16} />}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
