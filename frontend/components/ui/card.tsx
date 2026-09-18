import { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("rounded-2xl border border-line/80 bg-surface p-4 shadow-card", className)} {...props} />
  );
}
