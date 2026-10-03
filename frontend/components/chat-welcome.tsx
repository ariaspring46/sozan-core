"use client";

import { ArrowUpLeft, ImageIcon, MessageSquareText, Package, Store, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { SozanOrb } from "@/components/sozan-orb";

export type ChatStarter = { title: string; hint: string; text: string; icon: LucideIcon };

/** کارهای اصلی سوزان؛ لمس کارت جملهٔ شروع را در کادر می‌گذارد تا فروشنده کاملش کند و بفرستد. */
export const CHAT_STARTERS: readonly ChatStarter[] = [
  { icon: ImageIcon, title: "ساخت پست", hint: "عکس و کپشن آماده برای اینستاگرام و تلگرام", text: "یک پست اینستاگرام بساز برای " },
  { icon: Store, title: "فروشگاه", hint: "بساز، یا رنگ و متن و بخش‌هایش را عوض کن", text: "فروشگاهم را " },
  { icon: Package, title: "افزودن کالا", hint: "اسم و قیمت را بنویس، عکس هم بفرست", text: "این کالا را اضافه کن: " },
  { icon: MessageSquareText, title: "جواب دایرکت", hint: "دایرکت‌های اینستاگرام خودکار جواب بگیرند", text: "دایرکت‌های اینستاگرام را خودکار جواب بده" },
];

/** سلام خوشامد با وقت روز و نام فروشگاه («عصر بخیر، نقره‌خانه»)؛ خط دوم سوزان را معرفی می‌کند. */
export function greeting(brand: string, now = new Date()): string[] {
  const hour = now.getHours();
  const part = hour < 5 ? "شب" : hour < 12 ? "صبح" : hour < 17 ? "روز" : hour < 20 ? "عصر" : "شب";
  const name = brand.trim();
  return [`${part} بخیر${name ? `، ${name}` : ""}`, "من سوزانم؛ بگو امروز چه کاری برایت بکنم. کار مهم فقط با تأیید تو انجام می‌شود."];
}

/** صفحهٔ چت خالی: گوی سوزان با هاله و مدار (با نوشتن تو بیدار می‌شود)، سلام با عنوان درخشان، و کارت‌های شروع. */
export function ChatWelcome({
  lines,
  starters,
  excited = false,
  onPick,
}: {
  lines: string[];
  starters?: readonly ChatStarter[];
  /** فروشنده دارد می‌نویسد: گوی تندتر می‌چرخد و هاله روشن‌تر می‌شود. */
  excited?: boolean;
  onPick: (text: string) => void;
}) {
  const [title, ...rest] = lines;
  return (
    <div className="relative flex min-h-[min(66dvh,35rem)] flex-col items-center justify-center gap-5 pb-1 short:min-h-0 short:gap-4">
      <div className="sozan-float relative grid h-44 w-44 place-items-center short:h-32 short:w-32">
        <span aria-hidden className={cn("sozan-halo pointer-events-none absolute -inset-10 rounded-full transition-opacity duration-700 short:-inset-6", excited ? "opacity-100" : "opacity-75")} />
        <span aria-hidden className="sozan-orbit pointer-events-none absolute inset-1 rounded-full" />
        <span aria-hidden className="sozan-orbit sozan-orbit-b pointer-events-none absolute -inset-3 rounded-full" />
        <SozanOrb size={148} busy={excited} className="relative short:!h-24 short:!w-24" />
      </div>
      <div className="relative space-y-2.5 text-center">
        <h2 className="sozan-title-glow font-sozan text-[1.9rem] font-extrabold leading-tight short:text-2xl sm:text-4xl">{title}</h2>
        {rest.length ? <p className="mx-auto max-w-[21rem] text-[15px] leading-7 text-muted">{rest.join(" ")}</p> : null}
      </div>
      {starters?.length ? (
        <div className="relative grid w-full max-w-lg grid-cols-2 gap-3 lg:max-w-3xl lg:grid-cols-4" role="group" aria-label="شروع سریع">
          {starters.map((row, index) => {
            const Icon = row.icon;
            return (
              <button
                key={row.title}
                type="button"
                onClick={() => onPick(row.text)}
                className="sozan-card sozan-rise group flex min-h-[7rem] flex-col items-start gap-0.5 overflow-hidden rounded-[1.35rem] p-3.5 text-start transition duration-200 hover:-translate-y-0.5 active:scale-[0.97] short:min-h-0 short:p-3"
                style={{ animationDelay: `${140 + index * 70}ms` }}
              >
                <Icon aria-hidden size={88} strokeWidth={1.2} className="pointer-events-none absolute -bottom-5 -left-4 text-accent/[0.07] transition duration-500 group-hover:-rotate-6 group-hover:text-accent/[0.12]" />
                <span className="relative flex w-full items-start justify-between">
                  <span className="sozan-tile mb-1.5 flex h-10 w-10 items-center justify-center rounded-2xl">
                    <Icon size={19} aria-hidden />
                  </span>
                  <ArrowUpLeft size={16} aria-hidden className="text-muted/60 transition group-hover:-translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-warm" />
                </span>
                <span className="relative text-[15px] font-bold text-ink">{row.title}</span>
                <span className="relative line-clamp-2 text-[12.5px] leading-5 text-muted">{row.hint}</span>
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
