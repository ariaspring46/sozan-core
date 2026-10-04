"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

type Tally = {
  requests?: { ok?: number; "4xx"?: number; "5xx"?: number };
  otpSend?: Record<string, number>;
  llmFailed?: number;
  smsFailed?: number;
  tunnelDown?: number;
  crashes?: number;
};

type Health = {
  at: number;
  deployed: string;
  alerts: { level: "red" | "yellow"; text: string }[];
  services: Record<string, string>;
  machine: { diskFreeGb: number; diskUsedPct: number; memAvailableGb: number; load1: number; cpus: number };
  public: { apiCode: number; apiMs: number; apiError?: string; downSince: string };
  backups: { lastAgeHours: number | null; count?: number };
  logs: { hour: Tally; day: Tally; recent: string[] };
  ai: { spentTodayUsd: number | null; openrouterLeftUsd?: number | null; openrouterError?: string };
  people: { tenants: number; activeToday: number };
  shops: { mapped: number; containersUp: number };
};

const REFRESH_MS = 30_000;

function fa(n: number | null | undefined, digits = 0) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return Number(n).toLocaleString("fa-IR", { maximumFractionDigits: digits });
}

function otpLine(otp: Record<string, number> | undefined) {
  const sent = otp?.["200"] || 0;
  const failed = otp?.["502"] || 0;
  const limited = (otp?.["429"] || 0) + (otp?.["428"] || 0);
  return `${fa(sent)} ارسال · ${fa(failed)} شکست · ${fa(limited)} محدود/کپچا`;
}

function Tile({ label, value, bad, note }: { label: string; value: string; bad?: boolean; note?: string }) {
  return (
    <div className="min-w-0 rounded-xl border border-line bg-canvas p-3">
      <p className="text-xs text-muted">{label}</p>
      <p className={`mt-1 text-base font-bold tabular-nums ${bad ? "text-danger" : "text-ink"}`}>{value}</p>
      {note ? <p className="mt-0.5 text-xs text-muted">{note}</p> : null}
    </div>
  );
}

/** Hub health for the admin: alerts first, then the numbers behind them. Polls every 30 s while open. */
export function AdminHealth() {
  const [data, setData] = useState<Health | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api<Health>("/admin/health"));
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, REFRESH_MS);
    return () => window.clearInterval(id);
  }, [load]);

  if (!data) {
    return <p className="text-sm text-muted">{error || "در حال بررسی سرور…"}</p>;
  }

  const h = data.logs.hour;
  const d = data.logs.day;
  const servicesDown = Object.entries(data.services).filter(([, v]) => v !== "active");

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-muted">
          آخرین بررسی {new Date(data.at * 1000).toLocaleTimeString("fa-IR")} · نسخه <bdo dir="ltr">{data.deployed || "—"}</bdo>
        </p>
        <Button type="button" onClick={() => void load()} disabled={loading}>
          {loading ? "…" : "بررسی دوباره"}
        </Button>
      </div>
      {error ? <p className="text-sm text-danger" role="alert">{error}</p> : null}

      <section aria-label="هشدارها" className="space-y-2">
        {data.alerts.length ? (
          data.alerts.map((a, i) => (
            <p
              key={i}
              className={`rounded-xl border p-3 text-sm ${a.level === "red" ? "border-danger/40 bg-danger/10 text-danger" : "border-accent/40 bg-accent/10 text-warm"}`}
            >
              {a.level === "red" ? "●" : "○"} {a.text}
            </p>
          ))
        ) : (
          <p className="rounded-xl border border-signal/40 bg-signal/10 p-3 text-sm text-signal">● همه چیز سالم است</p>
        )}
      </section>

      <section className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Tile
          label="سایت از بیرون"
          value={data.public.apiCode === 200 ? `سالم · ${fa(data.public.apiMs)}ms` : `قطع (${data.public.apiCode || data.public.apiError})`}
          bad={data.public.apiCode !== 200}
        />
        <Tile
          label="سرویس‌ها"
          value={servicesDown.length ? servicesDown.map(([k]) => k).join("، ") : "همه فعال"}
          bad={servicesDown.length > 0}
        />
        <Tile label="ویترین‌های بالا" value={`${fa(data.shops.containersUp)} از ${fa(data.shops.mapped)}`} />
        <Tile
          label="پشتیبان شبانه"
          value={data.backups.lastAgeHours === null ? "ندارد" : `${fa(data.backups.lastAgeHours, 1)} ساعت پیش`}
          bad={data.backups.lastAgeHours === null || data.backups.lastAgeHours > 26}
          note="روی همین دیسک"
        />
        <Tile label="دیسک آزاد" value={`${fa(data.machine.diskFreeGb, 1)} گیگ`} bad={data.machine.diskFreeGb < 5} note={`${fa(data.machine.diskUsedPct)}٪ پر`} />
        <Tile label="حافظهٔ آزاد" value={`${fa(data.machine.memAvailableGb, 1)} گیگ`} note={`بار ${fa(data.machine.load1, 2)} روی ${fa(data.machine.cpus)} هسته`} />
        <Tile
          label="اعتبار اوپن‌روتر"
          value={data.ai.openrouterLeftUsd === null || data.ai.openrouterLeftUsd === undefined ? "نامعلوم" : `${fa(data.ai.openrouterLeftUsd, 2)} دلار`}
          bad={(data.ai.openrouterLeftUsd ?? 99) < 5}
          note={`خرج امروز ${fa(data.ai.spentTodayUsd, 4)} دلار`}
        />
        <Tile label="فروشنده‌ها" value={`${fa(data.people.activeToday)} فعال امروز`} note={`${fa(data.people.tenants)} حساب`} />
      </section>

      <section className="rounded-xl border border-line bg-canvas p-3 text-sm">
        <h2 className="mb-2 font-bold">یک ساعت گذشته / ۲۴ ساعت</h2>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5">
          <dt className="text-muted">کد ورود</dt>
          <dd className={h.smsFailed ? "text-danger" : ""}>
            {otpLine(h.otpSend)} <span className="text-muted">/ {otpLine(d.otpSend)}</span>
          </dd>
          <dt className="text-muted">خطای سرور (۵xx)</dt>
          <dd className={(h.requests?.["5xx"] || 0) > 0 ? "text-danger" : ""}>
            {fa(h.requests?.["5xx"])} <span className="text-muted">/ {fa(d.requests?.["5xx"])} از {fa(d.requests?.ok)} درخواست</span>
          </dd>
          <dt className="text-muted">شکست هوش مصنوعی</dt>
          <dd>
            {fa(h.llmFailed)} <span className="text-muted">/ {fa(d.llmFailed)}</span>
          </dd>
          <dt className="text-muted">قطعی تونل</dt>
          <dd>
            {fa(h.tunnelDown)} <span className="text-muted">/ {fa(d.tunnelDown)}</span>
          </dd>
          <dt className="text-muted">کرش (Traceback)</dt>
          <dd>
            {fa(h.crashes)} <span className="text-muted">/ {fa(d.crashes)}</span>
          </dd>
        </dl>
      </section>

      <section className="rounded-xl border border-line bg-canvas p-3">
        <h2 className="mb-2 text-sm font-bold">آخرین خطاها</h2>
        {data.logs.recent.length ? (
          <div className="overflow-x-auto">
            <ul className="space-y-1 font-mono text-xs" dir="ltr">
              {data.logs.recent
                .slice()
                .reverse()
                .map((line, i) => (
                  <li key={i} className="whitespace-pre-wrap break-all text-muted">
                    {line}
                  </li>
                ))}
            </ul>
          </div>
        ) : (
          <p className="text-sm text-muted">خطایی در ۲۴ ساعت گذشته نیست.</p>
        )}
      </section>
    </div>
  );
}
