"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState } from "@/components/empty-state";
import { api, fileUrl } from "@/lib/api";

type Ticket = {
  id: string;
  subject: string;
  text: string;
  orderNo?: string;
  image?: string;
  status: string;
  category?: string;
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

const CATEGORY_LABEL: Record<string, string> = {
  billing: "مالی",
  technical: "فنی",
  other: "متفرقه",
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
  const [ticketCategory, setTicketCategory] = useState("");
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
        api<{ tickets: Ticket[] }>("/settings/support/my-tickets").catch(() => ({ tickets: [] })),
        // only the hub admin may read every seller's tickets; asking as a seller logged a 403 on every visit
        api<{ isAdmin?: boolean }>("/auth/me")
          .then((me) => (me.isAdmin ? api<{ tickets: Ticket[] }>("/settings/support/hub") : null))
          .catch(() => null),
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
      await api("/settings/support/seller-ticket", {
        method: "POST",
        body: JSON.stringify({
          subject: ticketSubject.trim(),
          text: ticketText.trim(),
          category: ticketCategory,
        }),
      });
      setTicketCategory("");
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
      await api(`/settings/support/hub/${id}/reply`, { method: "POST", body: JSON.stringify({ text, status }) });
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
            <Link href="/more" className="tap text-warm">
              بیشتر
            </Link>
          </p>
          <h1 className="text-lg font-bold">پشتیبانی و رسیدها</h1>
        </div>
      }
    >
      <div className="h-full space-y-4 overflow-y-auto p-4 [&>*]:mx-auto [&>*]:max-w-3xl">
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
                  <p className="wrap-any text-sm font-medium">
                    {row.title || "سفارش"} · {Number(row.amount || 0).toLocaleString("fa-IR")} تومان
                  </p>
                  <p className="wrap-any mt-0.5 text-xs text-muted">
                    سفارش <bdi dir="ltr">{row.id}</bdi>
                    {row.customer ? ` · ${row.customer}` : ""}
                  </p>
                  {row.receipt ? (
                    <a
                      className="mt-1 inline-flex min-h-11 items-center text-sm text-warm underline"
                      href={fileUrl("", `media/${row.receipt}`)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      دیدن عکس رسید
                    </a>
                  ) : (
                    <p className="mt-1 text-xs text-muted">بدون عکس</p>
                  )}
                  <Input
                    className="mt-2"
                    placeholder="یادداشت برای خریدار (اختیاری)"
                    aria-label="یادداشت برای خریدار"
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
            <p className="mt-2 text-sm text-muted">رسیدی در انتظار نیست.</p>
          )}
        </section>

        <section aria-labelledby="sozan-title" className="rounded-2xl border border-line bg-paper p-4 shadow-card">
          <h2 id="sozan-title" className="font-bold">
            تیکت به پشتیبانی سوزان
          </h2>
          <div className="mt-3 space-y-2">
            <Select
              aria-label="دستهٔ تیکت"
              value={ticketCategory}
              onChange={(e) => setTicketCategory(e.target.value)}
            >
              <option value="">دسته را انتخاب کن</option>
              <option value="billing">مالی</option>
              <option value="technical">فنی</option>
              <option value="other">متفرقه</option>
            </Select>
            <Input
              placeholder="موضوع"
              aria-label="موضوع تیکت"
              value={ticketSubject}
              onChange={(e) => setTicketSubject(e.target.value)}
            />
            <Textarea
              className="min-h-24"
              placeholder="مشکل یا پرسش‌ات را بنویس"
              aria-label="متن تیکت"
              value={ticketText}
              onChange={(e) => setTicketText(e.target.value)}
            />
            <Button
              disabled={busy || !ticketCategory || !ticketSubject.trim() || !ticketText.trim()}
              onClick={() => void sendToSozan()}
            >
              فرستادن به سوزان
            </Button>
          </div>
          {mine.length ? (
            <ul className="mt-3 space-y-2">
              {mine.map((row) => (
                <li key={row.id} className="rounded-xl border border-line bg-canvas p-3 text-sm">
                  <p className="font-bold">
                    {row.subject}{" "}
                    <span className="text-xs font-normal text-muted">
                      · {CATEGORY_LABEL[row.category || "other"] || "متفرقه"} · {STATUS_LABEL[row.status] || row.status}
                    </span>
                  </p>
                  <p className="mt-1 whitespace-pre-line leading-6">{row.text}</p>
                  {(row.replies || []).map((rep, idx) => (
                    <p key={idx} className="wrap-any mt-2 rounded-lg bg-paper p-2 text-sm leading-7">
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
                      {row.orderNo ? <> · سفارش <bdi dir="ltr">{row.orderNo}</bdi></> : null}
                    </span>
                  </p>
                  <p className="mt-1 whitespace-pre-line text-sm leading-7">{row.text}</p>
                  {(row.replies || []).map((rep, idx) => (
                    <p key={idx} className="wrap-any mt-2 rounded-lg bg-paper p-2 text-sm leading-7">
                      پاسخ شما: {rep.text}
                    </p>
                  ))}
                  <Input
                    className="mt-2"
                    placeholder="پاسخ به مشتری"
                    aria-label="پاسخ به مشتری"
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
                        · {CATEGORY_LABEL[row.category || "other"] || "متفرقه"} · {STATUS_LABEL[row.status] || row.status}{" "}
                        · فروشندهٔ <bdo dir="ltr">{row.tenant}</bdo>
                      </span>
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
                        placeholder="پاسخ پشتیبانی سوزان"
                        aria-label="پاسخ پشتیبانی سوزان"
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
