"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/empty-state";
import { api, fileUrl } from "@/lib/api";

type Ticket = {
  id: string;
  subject: string;
  text: string;
  orderNo?: string;
  image?: string;
  status: string;
  replies?: { text: string; at: number }[];
  at: number;
  tenant?: string;
};

type Receipt = {
  id: string;
  title?: string;
  amount?: number;
  status?: string;
  receipt?: string;
  customer?: string;
};

const STATUS_LABEL: Record<string, string> = {
  open: "باز",
  working: "در حال بررسی",
  closed: "بسته",
};

function faTime(at: number) {
  return new Date(at * 1000).toLocaleDateString("fa-IR");
}

/** تیکت‌های ویترین و رسیدهای کارت‌به‌کارت در انتظار تأیید. */
export default function SupportPage() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [mine, setMine] = useState<Ticket[]>([]);
  const [hubView, setHubView] = useState<Ticket[] | null>(null);
  const [ticketSubject, setTicketSubject] = useState("");
  const [ticketText, setTicketText] = useState("");
  const [reply, setReply] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [t, r, m, hub] = await Promise.all([
        api<{ tickets: Ticket[] }>("/support/tickets"),
        api<{ receipts: Receipt[] }>("/pay/receipts"),
        api<{ tickets: Ticket[] }>("/support/my-tickets").catch(() => ({ tickets: [] })),
        api<{ tickets: Ticket[] }>("/support/hub").catch(() => null),
      ]);
      setTickets(t.tickets || []);
      setReceipts(r.receipts || []);
      setMine(m.tickets || []);
      setHubView(hub === null ? null : hub.tickets || []);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function sendReply(id: string, status: string) {
    const text = reply[id] || "";
    if (!text.trim() && status === "working") return;
    setBusy(true);
    try {
      await api(`/support/tickets/${id}/reply`, {
        method: "POST",
        body: JSON.stringify({ text, status }),
      });
      setReply((row) => ({ ...row, [id]: "" }));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  async function sendToSozan() {
    if (!ticketSubject.trim() || !ticketText.trim()) return;
    setBusy(true);
    try {
      await api("/support/seller-ticket", {
        method: "POST",
        body: JSON.stringify({ subject: ticketSubject.trim(), text: ticketText.trim() }),
      });
      setTicketSubject("");
      setTicketText("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  async function hubReply(id: string, text: string, status: string) {
    setBusy(true);
    try {
      await api(`/support/hub/${id}/reply`, { method: "POST", body: JSON.stringify({ text, status }) });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  async function review(orderNo: string, approve: boolean) {
    const note = reply[`r-${orderNo}`] || "";
    setBusy(true);
    try {
      await api(`/pay/receipts/${orderNo}/review`, {
        method: "POST",
        body: JSON.stringify({ approve, note }),
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell
      header={
        <div>
          <p className="text-sm text-muted">
            <Link href="/more" className="text-warm">
              بیشتر
            </Link>
          </p>
          <h1 className="text-lg font-bold">پشتیبانی و رسیدها</h1>
        </div>
      }
    >
      <div className="h-full space-y-4 overflow-y-auto p-4">
        {error ? (
          <p className="text-sm text-danger" role="alert">
            {error}
          </p>
        ) : null}

        <section aria-labelledby="receipts-title" className="rounded-2xl border border-line bg-paper p-4 shadow-card">
          <h2 id="receipts-title" className="font-bold">
            رسیدهای کارت‌به‌کارت در انتظار تأیید
          </h2>
          {receipts.length ? (
            <ul className="mt-3 space-y-3">
              {receipts.map((row) => (
                <li key={row.id} className="rounded-xl border border-line bg-canvas p-3">
                  <p className="text-sm">
                    سفارش <bdo dir="ltr">{row.id}</bdo> · {row.title} ·{" "}
                    {Number(row.amount || 0).toLocaleString("fa-IR")} تومان · {row.customer}
                  </p>
                  {row.receipt ? (
                    <a
                      className="mt-1 block text-xs text-warm underline"
                      href={fileUrl("", `media/${row.receipt}`)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      دیدن عکس رسید
                    </a>
                  ) : (
                    <p className="mt-1 text-xs text-muted">بدون عکس</p>
                  )}
                  <input
                    className="mt-2 w-full rounded-xl border border-line bg-paper px-3 py-2 text-sm"
                    placeholder="یادداشت برای خریدار (اختیاری)"
                    value={reply[`r-${row.id}`] || ""}
                    onChange={(e) => setReply((rows) => ({ ...rows, [`r-${row.id}`]: e.target.value }))}
                  />
                  <div className="mt-2 flex gap-2">
                    <Button disabled={busy} onClick={() => void review(row.id, true)}>
                      تأیید پرداخت
                    </Button>
                    <Button variant="ghost" disabled={busy} onClick={() => void review(row.id, false)}>
                      رد رسید
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-xs text-muted">رسیدی در انتظار نیست.</p>
          )}
        </section>

        <section aria-labelledby="sozan-title" className="rounded-2xl border border-line bg-paper p-4 shadow-card">
          <h2 id="sozan-title" className="font-bold">
            تیکت به پشتیبانی سوزان
          </h2>
          <div className="mt-3 space-y-2">
            <input
              className="w-full rounded-xl border border-line bg-canvas px-3 py-2 text-sm"
              placeholder="موضوع"
              value={ticketSubject}
              onChange={(e) => setTicketSubject(e.target.value)}
            />
            <textarea
              className="min-h-24 w-full rounded-xl border border-line bg-canvas px-3 py-2 text-sm"
              placeholder="مشکل یا پرسش‌ات را بنویس"
              value={ticketText}
              onChange={(e) => setTicketText(e.target.value)}
            />
            <Button disabled={busy || !ticketSubject.trim() || !ticketText.trim()} onClick={() => void sendToSozan()}>
              فرستادن به سوزان
            </Button>
          </div>
          {mine.length ? (
            <ul className="mt-3 space-y-2">
              {mine.map((row) => (
                <li key={row.id} className="rounded-xl border border-line bg-canvas p-3 text-sm">
                  <p className="font-bold">
                    {row.subject}{" "}
                    <span className="text-xs font-normal text-muted">· {STATUS_LABEL[row.status] || row.status}</span>
                  </p>
                  <p className="mt-1 whitespace-pre-line leading-6">{row.text}</p>
                  {(row.replies || []).map((rep, idx) => (
                    <p key={idx} className="mt-2 rounded-lg bg-paper p-2 text-xs leading-6">
                      پاسخ پشتیبانی: {rep.text}
                    </p>
                  ))}
                </li>
              ))}
            </ul>
          ) : null}
        </section>

        <section aria-labelledby="tickets-title" className="rounded-2xl border border-line bg-paper p-4 shadow-card">
          <h2 id="tickets-title" className="font-bold">
            تیکت‌های مشتریان
          </h2>
          {tickets.length ? (
            <ul className="mt-3 space-y-3">
              {tickets.map((row) => (
                <li key={row.id} className="rounded-xl border border-line bg-canvas p-3">
                  <p className="text-sm font-bold">
                    {row.subject}{" "}
                    <span className="text-xs font-normal text-muted">
                      · {STATUS_LABEL[row.status] || row.status} · {faTime(row.at)}
                      {row.orderNo ? ` · سفارش ${row.orderNo}` : ""}
                    </span>
                  </p>
                  <p className="mt-1 whitespace-pre-line text-sm leading-7">{row.text}</p>
                  {(row.replies || []).map((rep, idx) => (
                    <p key={idx} className="mt-2 rounded-lg bg-paper p-2 text-xs leading-6">
                      پاسخ شما: {rep.text}
                    </p>
                  ))}
                  <input
                    className="mt-2 w-full rounded-xl border border-line bg-paper px-3 py-2 text-sm"
                    placeholder="پاسخ به مشتری"
                    value={reply[row.id] || ""}
                    onChange={(e) => setReply((rows) => ({ ...rows, [row.id]: e.target.value }))}
                  />
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Button disabled={busy || !(reply[row.id] || "").trim()} onClick={() => void sendReply(row.id, "working")}>
                      فرستادن پاسخ
                    </Button>
                    <Button variant="ghost" disabled={busy} onClick={() => void sendReply(row.id, "closed")}>
                      بستن تیکت
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="تیکتی نیست" detail="پیام‌های پشتیبانی مشتریان اینجا می‌آید." />
          )}
        </section>
        {hubView !== null ? (
          <section aria-labelledby="hub-title" className="rounded-2xl border border-accent/40 bg-paper p-4 shadow-card">
            <h2 id="hub-title" className="font-bold">
              پشتیبانی سوزان — تیکت‌های فروشندگان
            </h2>
            {hubView.length ? (
              <ul className="mt-3 space-y-3">
                {hubView.map((row) => (
                  <li key={row.id} className="rounded-xl border border-line bg-canvas p-3 text-sm">
                    <p className="font-bold">
                      {row.subject}{" "}
                      <span className="text-xs font-normal text-muted">
                        · {STATUS_LABEL[row.status] || row.status} · فروشندهٔ {String(row.tenant || "").slice(0, 4)}
                        ***
                      </span>
                    </p>
                    <p className="mt-1 whitespace-pre-line leading-6">{row.text}</p>
                    {(row.replies || []).map((rep, idx) => (
                      <p key={idx} className="mt-2 rounded-lg bg-paper p-2 text-xs leading-6">
                        پاسخ قبلی: {rep.text}
                      </p>
                    ))}
                    <div className="mt-2 flex flex-wrap gap-2">
                      <input
                        className="min-w-40 flex-1 rounded-xl border border-line bg-paper px-3 py-2 text-sm"
                        placeholder="پاسخ پشتیبانی سوزان"
                        value={reply[`h-${row.id}`] || ""}
                        onChange={(e) => setReply((rows) => ({ ...rows, [`h-${row.id}`]: e.target.value }))}
                      />
                      <Button
                        disabled={busy || !(reply[`h-${row.id}`] || "").trim()}
                        onClick={() => void hubReply(row.id, reply[`h-${row.id}`] || "", "working")}
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
              <p className="mt-2 text-xs text-muted">تیکتی نیست.</p>
            )}
          </section>
        ) : null}
      </div>
    </AppShell>
  );
}
