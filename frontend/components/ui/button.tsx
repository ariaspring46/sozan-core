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
        "inline-flex min-h-11 items-center justify-center rounded-xl px-4 text-sm font-medium disabled:cursor-not-allowed",
        variant === "ghost"
          ? "border border-line bg-paper text-ink hover:bg-canvas disabled:border-line disabled:bg-canvas disabled:text-muted"
          : "bg-accentStrong text-onAccent hover:bg-accent disabled:border disabled:border-line disabled:bg-canvas disabled:text-muted disabled:hover:bg-canvas",
        className,
      )}
      {...props}
    />
  );
}
