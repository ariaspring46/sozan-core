"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export function TrainingChoice() {
  const [on, setOn] = useState(true);

  useEffect(() => {
    void api<{ helpImprove?: boolean }>("/settings")
      .then((data) => setOn(data.helpImprove !== false))
      .catch(() => setOn(true));
  }, []);

  return (
    <section aria-label="کمک به بهتر شدن سوزان" className="rounded-2xl border border-line/80 bg-surface p-4 shadow-card">
      <label className="flex min-h-11 items-start gap-3 text-sm">
        <input
          type="checkbox"
          className="mt-1 h-5 w-5 shrink-0 accent-accent"
          checked={on}
          onChange={(event) => {
            const next = event.target.checked;
            setOn(next);
            void api("/settings", { method: "PATCH", body: JSON.stringify({ helpImprove: next }) }).catch(() =>
              setOn(!next),
            );
          }}
        />
        <span>
          <span className="block font-bold">کمک به بهتر شدن سوزان</span>
          <span className="mt-1 block text-muted">
            برای بهتر شدن سوزان، گفتگوها پس از حذف اطلاعات شخصی ممکن است برای آموزش مدل‌های سوزان استفاده شود. این گزینه
            در تنظیمات قابل خاموش کردن است.
          </span>
        </span>
      </label>
    </section>
  );
}
