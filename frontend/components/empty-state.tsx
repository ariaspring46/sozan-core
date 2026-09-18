import { ReactNode } from "react";

export function EmptyState({
  title,
  detail,
  action,
}: {
  title: string;
  detail?: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-dashed border-line bg-paper px-4 py-10 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      {detail ? <p className="mt-1 text-sm leading-7 text-muted">{detail}</p> : null}
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}
