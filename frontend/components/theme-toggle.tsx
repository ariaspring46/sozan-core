"use client";

import { useEffect, useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";
import { readTheme, saveTheme, type ThemeChoice } from "@/lib/theme";

const OPTIONS: { id: ThemeChoice; label: string; icon: typeof Sun }[] = [
  { id: "light", label: "روشن", icon: Sun },
  { id: "dark", label: "تیره", icon: Moon },
  { id: "system", label: "خودکار", icon: Monitor },
];

/** انتخاب تم پنل: روشن، تیره یا همان تنظیم دستگاه. */
export function ThemeToggle({ compact = false, className }: { compact?: boolean; className?: string }) {
  const [choice, setChoice] = useState<ThemeChoice>("system");

  useEffect(() => {
    setChoice(readTheme());
  }, []);

  return (
    <div role="radiogroup" aria-label="تم پنل" className={cn("flex gap-1 rounded-xl border border-line bg-paper p-1", className)}>
      {OPTIONS.map((option) => {
        const Icon = option.icon;
        const active = choice === option.id;
        return (
          <button
            key={option.id}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={option.label}
            title={option.label}
            onClick={() => {
              setChoice(option.id);
              saveTheme(option.id);
            }}
            className={cn(
              "flex min-h-9 flex-1 items-center justify-center gap-1.5 rounded-lg px-2 text-xs",
              active ? "bg-canvas font-bold text-ink shadow-card" : "text-muted hover:text-ink",
            )}
          >
            <Icon size={15} aria-hidden />
            {compact ? null : <span>{option.label}</span>}
          </button>
        );
      })}
    </div>
  );
}
