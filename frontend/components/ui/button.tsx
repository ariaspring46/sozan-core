import { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export function Button({
  className,
  variant = "primary",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" }) {
  return (
    <button
      className={cn(
        "inline-flex min-h-11 items-center justify-center rounded-xl px-4 text-sm font-medium disabled:opacity-50",
        variant === "ghost"
          ? "border border-line bg-paper text-ink hover:bg-canvas"
          : "bg-accent text-onAccent hover:bg-warm",
        className,
      )}
      {...props}
    />
  );
}
