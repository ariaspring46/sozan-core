"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState } from "@/components/empty-state";
import { AdminHealth } from "@/components/admin-health";
import { api } from "@/lib/api";

type UserRow = {
  phone: string;
  plan: string;
  paidUntil: number;
  daysLeft: number;
  status: string;
  sites: number;
  channels: number;
  aiToday: number;
  aiWeek: number;
  lastActivity: number;
  blocked?: boolean;
  name?: string;
  brand?: string;
  pages?: string[];
  shopHost?: string;
};

type UserDetail = UserRow & {
  billing: { plan: string; amount: number; status: string; at: number; refId: string; coupon: string }[];
  orders: { id: string; amount: number; status: string; at: number }[];
  tickets: { id: string; subject: string; status: string; at: number }[];
  site: { slug: string; status: string; publicHost: string };
};

type PaymentsData = {
  rows: { phone: string; plan: string; amount: number; at: number; refId: string }[];
  totals: { today: number; week: number; month: number; all: number };
  byPlan: Record<string, number>;
};

const STATUS_LABEL: Record<string, string> = { active: "فعال", blocked: "مسدود", expired: "منقضی" };

type HubTicket = {
  id: string;
  subject: string;
  text: string;
  status: string;
  category?: string;
  tenant?: string;
  replies?: { text: string }[];
};

const TICKET_STATUS: Record<string, string> = { open: "باز", working: "در حال بررسی", closed: "بسته" };
const TICKET_CATEGORY: Record<string, string> = { billing: "مالی", technical: "فنی", other: "متفرقه" };

function fa(n: number) {
  return Number(n || 0).toLocaleString("fa-IR");
}

function faDate(ts: number) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleDateString("fa-IR");
}

export default function AdminPage() {
  const [tab, setTab] = useState<"health" | "users" | "payments" | "audit" | "tickets">("health");
  const [users, setUsers] = useState<UserRow[]>([]);
  const [payments, setPayments] = useState<PaymentsData | null>(null);
  const [audit, setAudit] = useState<{ action: string; target: string; reason: string; at: number }[]>([]);
  const [detail, setDetail] = useState<UserDetail | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [planForm, setPlanForm] = useState<Record<string, string>>({});
  const [search, setSearch] = useState("");
  const [hubTickets, setHubTickets] = useState<HubTicket[]>([]);
  const [ticketFilter, setTicketFilter] = useState<"" | "billing" | "technical" | "other">("");
  const [ticketReply, setTicketReply] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      const [u, p, a] = await Promise.all([
        api<{ users: UserRow[] }>("/admin/users"),
        api<PaymentsData>("/admin/payments"),
        api<{ actions: typeof audit }>("/admin/audit"),
      ]);
      setUsers(u.users || []);
      setPayments(p);
      setAudit(a.actions || []);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    }
  }, []);

  const loadTickets = useCallback(async () => {
    try {
      const hub = await api<{ tickets: HubTicket[] }>("/settings/support/hub");
      setHubTickets(hub.tickets || []);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (tab !== "tickets") return;
    void loadTickets();
  }, [tab, loadTickets]);

  async function openDetail(phone: string) {
    try {
      const d = await api<UserDetail>(`/admin/users/${encodeURIComponent(phone)}`);
      setDetail(d);
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    }
  }

  async function submitPlan(phone: string) {
    const plan = planForm[`${phone}:plan`] || "pro";
    const days = planForm[`${phone}:days`] || "30";
    const reason = planForm[`${phone}:reason`] || "";
    if (!reason.trim()) return;
    setBusy(true);
    try {
      await api(`/admin/users/${encodeURIComponent(phone)}/plan`, {
        method: "POST",
        body: JSON.stringify({ plan, days: Number(days), reason }),
      });
      setPlanForm((r) => ({ ...r, [`${phone}:reason`]: "" }));
      await load();
      await openDetail(phone);
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  async function toggleBlock(phone: string, blocked: boolean) {
    const reason = planForm[`${phone}:blockReason`] || "";
    if (!reason.trim()) return;
    setBusy(true);
    try {
      await api(`/admin/users/${encodeURIComponent(phone)}/block`, {
        method: "POST",
        body: JSON.stringify({ blocked, reason }),
      });
      setPlanForm((r) => ({ ...r, [`${phone}:blockReason`]: "" }));
      await load();
      await openDetail(phone);
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  async function hubReply(id: string, text: string, status: string) {
    setBusy(true);
    try {
      await api(`/settings/support/hub/${id}/reply`, { method: "POST", body: JSON.stringify({ text, status }) });
      setTicketReply((rows) => ({ ...rows, [id]: "" }));
      await loadTickets();
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  const needle = search.trim().toLowerCase();
  const visibleTickets = hubTickets.filter((row) => !ticketFilter || (row.category || "other") === ticketFilter);
  const filtered = users.filter(
    (u) =>
      !needle ||
      [u.phone, u.plan, u.name, u.brand, u.shopHost, ...(u.pages || [])].some((v) => String(v || "").toLowerCase().includes(needle)),
  );

  if (/فقط برای مدیر/.test(error)) {
    return (
      <AppShell
        header={
          <div>
            <p className="text-sm text-muted">مدیریت سوزان</p>
            <h1 className="text-lg font-bold">پیشخوان مدیر</h1>
          </div>
        }
      >
        <div className="h-full overflow-y-auto p-4">
          <EmptyState
            title="این بخش فقط برای مدیر سوزان است"
            detail="با حساب فروشنده به این صفحه دسترسی نداری."
            action={
              <Link href="/chat" className="inline-flex min-h-11 items-center rounded-xl bg-accentStrong px-4 text-sm text-onAccent">
                رفتن به چت
              </Link>
            }
          />
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell
      header={
        <div>
          <p className="text-sm text-muted">مدیریت سوزان</p>
          <h1 className="text-lg font-bold">پیشخوان مدیر</h1>
        </div>
      }
    >
      <div className="h-full space-y-4 overflow-y-auto p-4">
        {error ? <p className="text-sm text-danger" role="alert">{error}</p> : null}

        <div className="flex flex-wrap gap-2">
          {(["health", "users", "payments", "audit", "tickets"] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={`min-h-11 rounded-xl px-4 text-sm ${tab === t ? "border border-accent/40 bg-accent/15 text-warm" : "border border-line text-muted"}`}
            >
              {t === "health" ? "سلامت" : t === "users" ? "کاربران" : t === "payments" ? "پرداخت‌ها" : t === "audit" ? "اقدامات" : "تیکت‌ها"}
            </button>
          ))}
        </div>

        {tab === "health" ? <AdminHealth /> : null}

        {tab === "users" ? (
          <>
            <Input
              placeholder="جستجو: نام، برند، پیج، شماره یا پلن"
              aria-label="جستجوی کاربر"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            {filtered.length ? (
              <ul className="space-y-2">
                {filtered.map((u) => (
                  <li key={u.phone} className="rounded-xl border border-line bg-canvas p-3">
                    <button type="button" className="min-h-11 w-full text-start" onClick={() => void openDetail(u.phone)}>
                      <p className="text-sm font-bold">
                        {u.name || u.brand ? <span className="me-2">{u.name || "بی‌نام"}{u.brand ? ` · ${u.brand}` : ""}</span> : null}
                        <bdo dir="ltr" className="text-muted">{u.phone}</bdo>
                        <span className={`ms-2 text-xs ${u.status === "active" ? "text-signal" : "text-danger"}`}>
                          · {STATUS_LABEL[u.status] || u.status}
                        </span>
                      </p>
                      <p className="mt-1 text-xs text-muted">
                        {u.plan} · {u.daysLeft > 0 ? `${fa(u.daysLeft)} روز مانده` : "بدون انقضا"}
                        {u.daysLeft > 0 ? ` (${faDate(u.paidUntil)})` : ""}
                        {` · ${fa(u.sites)} سایت · ${fa(u.channels)} کانال`}
                        {` · ابر: $${u.aiToday?.toFixed(3) || 0} امروز`}
                      </p>
                      {u.pages?.length || u.shopHost ? (
                        <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs" dir="ltr">
                          {(u.pages || []).map((pg) => (
                            <span key={pg} className="text-warm">{pg.replace(/^instagram:/, "IG ").replace(/^telegram:/, "TG ")}</span>
                          ))}
                          {u.shopHost ? <span className="text-muted">{u.shopHost}</span> : null}
                        </p>
                      ) : null}
                    </button>
                    {detail?.phone === u.phone ? (
                      <div className="mt-3 space-y-3 border-t border-line pt-3">
                        <div>
                          <p className="text-xs font-bold">پرداخت‌ها ({fa(detail.billing?.length || 0)})</p>
                          {(detail.billing || []).slice(-5).map((b, i) => (
                            <p key={i} className="text-xs text-muted">
                              {faDate(b.at)} · {b.plan} · {fa(b.amount)} تومان · {b.status}
                              {b.refId ? ` · ${b.refId}` : ""}
                            </p>
                          ))}
                        </div>
                        <div>
                          <p className="text-xs font-bold">سفارش‌ها ({fa(detail.orders?.length || 0)}) · تیکت‌ها ({fa(detail.tickets?.length || 0)})</p>
                          {detail.site?.slug ? (
                            <p className="text-xs text-muted">فروشگاه: {detail.site.slug} ({detail.site.status})</p>
                          ) : null}
                        </div>
                        <div className="space-y-2 rounded-lg bg-paper p-2">
                          <p className="text-xs font-bold">تغییر پلن</p>
                          <div className="flex gap-2">
                            <select
                              className="rounded-lg border border-line bg-canvas px-2 py-1 text-xs"
                              value={planForm[`${u.phone}:plan`] || "pro"}
                              onChange={(e) => setPlanForm((r) => ({ ...r, [`${u.phone}:plan`]: e.target.value }))}
                            >
                              <option value="free">رایگان</option>
                              <option value="pro">پرو</option>
                              <option value="promax">پرومکس</option>
                              <option value="ultra">اولترا</option>
                            </select>
                            <input
                              type="number"
                              min={0}
                              max={365}
                              className="w-20 rounded-lg border border-line bg-canvas px-2 py-1 text-xs"
                              placeholder="روز"
                              value={planForm[`${u.phone}:days`] || "30"}
                              onChange={(e) => setPlanForm((r) => ({ ...r, [`${u.phone}:days`]: e.target.value }))}
                            />
                          </div>
                          <input
                            className="w-full rounded-lg border border-line bg-canvas px-2 py-1 text-xs"
                            placeholder="دلیل (اجباری)"
                            value={planForm[`${u.phone}:reason`] || ""}
                            onChange={(e) => setPlanForm((r) => ({ ...r, [`${u.phone}:reason`]: e.target.value }))}
                          />
                          <Button disabled={busy || !(planForm[`${u.phone}:reason`] || "").trim()} onClick={() => void submitPlan(u.phone)}>
                            ثبت پلن
                          </Button>
                        </div>
                        <div className="space-y-2 rounded-lg bg-paper p-2">
                          <p className="text-xs font-bold">{detail.blocked ? "فعال‌سازی" : "مسدودسازی"}</p>
                          <input
                            className="w-full rounded-lg border border-line bg-canvas px-2 py-1 text-xs"
                            placeholder="دلیل (اجباری)"
                            value={planForm[`${u.phone}:blockReason`] || ""}
                            onChange={(e) => setPlanForm((r) => ({ ...r, [`${u.phone}:blockReason`]: e.target.value }))}
                          />
                          <Button
                            variant="ghost"
                            disabled={busy || !(planForm[`${u.phone}:blockReason`] || "").trim()}
                            onClick={() => void toggleBlock(u.phone, !detail.blocked)}
                          >
                            {detail.blocked ? "فعال کن" : "مسدود کن"}
                          </Button>
                        </div>
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="کاربری نیست" detail="لیست کاربران سوزان اینجا می‌آید." />
            )}
          </>
        ) : null}

        {tab === "payments" && payments ? (
          <>
            <div className="rounded-xl border border-line bg-canvas p-3 text-sm">
              <p>امروز: {fa(payments.totals.today)} تومان</p>
              <p>هفته: {fa(payments.totals.week)} · ماه: {fa(payments.totals.month)} · کل: {fa(payments.totals.all)}</p>
              {Object.entries(payments.byPlan).map(([plan, amount]) => (
                <p key={plan} className="text-xs text-muted">{plan}: {fa(amount)} تومان</p>
              ))}
            </div>
            <ul className="space-y-1">
              {payments.rows.map((r, i) => (
                <li key={i} className="rounded-lg bg-canvas p-2 text-xs">
                  <bdo dir="ltr">{r.phone}</bdo> · {r.plan} · {fa(r.amount)} تومان · {faDate(r.at)}
                  {r.refId ? ` · ref: ${r.refId}` : ""}
                </li>
              ))}
            </ul>
          </>
        ) : null}

        {tab === "tickets" ? (
          <>
            <div className="flex flex-wrap gap-2">
              {(
                [
                  ["", "همه"],
                  ["billing", "مالی"],
                  ["technical", "فنی"],
                  ["other", "متفرقه"],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value || "all"}
                  type="button"
                  onClick={() => setTicketFilter(value)}
                  className={`min-h-11 rounded-xl px-3 text-sm ${ticketFilter === value ? "border border-accent/40 bg-accent/15 text-warm" : "border border-line text-muted"}`}
                >
                  {label}
                </button>
              ))}
            </div>
            {visibleTickets.length ? (
              <ul className="space-y-3">
                {visibleTickets.map((row) => (
                  <li key={`${row.tenant}-${row.id}`} className="rounded-xl border border-line bg-canvas p-3 text-sm">
                    <p className="font-bold">
                      {row.subject}{" "}
                      <span className="text-xs font-normal text-muted">
                        · {TICKET_CATEGORY[row.category || "other"] || "متفرقه"} · {TICKET_STATUS[row.status] || row.status}
                      </span>
                    </p>
                    <p className="mt-1 text-xs text-muted">
                      فروشندهٔ <bdo dir="ltr">{row.tenant}</bdo>
                    </p>
                    <p className="mt-1 whitespace-pre-line leading-6">{row.text}</p>
                    {(row.replies || []).map((rep, idx) => (
                      <p key={idx} className="mt-2 rounded-lg bg-paper p-2 text-xs leading-6">
                        پاسخ قبلی: {rep.text}
                      </p>
                    ))}
                    <div className="mt-2 flex flex-wrap gap-2">
                      <Input
                        className="min-w-40 flex-1"
                        placeholder="پاسخ پشتیبانی"
                        aria-label="پاسخ پشتیبانی"
                        value={ticketReply[row.id] || ""}
                        onChange={(e) => setTicketReply((rows) => ({ ...rows, [row.id]: e.target.value }))}
                      />
                      <Button
                        disabled={busy || !(ticketReply[row.id] || "").trim()}
                        onClick={() => void hubReply(row.id, ticketReply[row.id] || "", "working")}
                      >
                        پاسخ
                      </Button>
                      <Button variant="ghost" disabled={busy} onClick={() => void hubReply(row.id, "", "closed")}>
                        بستن
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="تیکتی نیست" detail="تیکت‌های فروشندگان به سوزان اینجا می‌آید." />
            )}
          </>
        ) : null}

        {tab === "audit" ? (
          <ul className="space-y-1">
            {audit.map((a, i) => (
              <li key={i} className="rounded-lg bg-canvas p-2 text-xs">
                {faDate(a.at)} · {a.action} · <bdo dir="ltr">{a.target}</bdo>
                {a.reason ? ` · ${a.reason}` : ""}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </AppShell>
  );
}
