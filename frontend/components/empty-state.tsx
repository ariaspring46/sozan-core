import { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

export function EmptyState({
  title,
  detail,
  action,
  icon: Icon,
}: {
  title: string;
  detail?: string;
  action?: ReactNode;
  icon?: LucideIcon;
}) {
  return (
    <div className="rounded-2xl border border-line bg-surface px-5 py-10 text-center">
      {Icon ? (
        <span className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-accent/10 text-warm">
          <Icon className="h-6 w-6" aria-hidden />
        </span>
      ) : null}
      <p className="font-bold text-ink">{title}</p>
      {detail ? <p className="mx-auto mt-1 max-w-sm text-sm leading-7 text-muted">{detail}</p> : null}
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}
