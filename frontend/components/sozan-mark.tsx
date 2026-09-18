import { cn } from "@/lib/utils";

export function SozanMark({ className, glow = true }: { className?: string; glow?: boolean }) {
  return (
    <span className={cn("inline-flex shrink-0", className)}>
      <img
        src="/sozan-mark.png?v=copper-1"
        alt="سوزان"
        width={112}
        height={112}
        className={cn(
          "h-full w-full object-contain",
          glow && "drop-shadow-[0_0_18px_rgb(196_92_38_/_45%)]",
        )}
      />
    </span>
  );
}
