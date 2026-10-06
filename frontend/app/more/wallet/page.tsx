"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { Field } from "@/components/field";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { formatWhen, money, parseNonNegativeInt, toLatinDigits } from "@/lib/digits";
import { EmptyState } from "@/components/empty-state";

type LedgerRow = { id: string; at: number; kind: string; amount: number; note?: string; orderId?: string };
type WithdrawRow = {
  id: string;
  at: number;
  amount: number;
  iban: string;
  name?: string;
  status: string;
  phone?: string;
};
type WalletSnap = {
  available: number;
  pendingWithdraw: number;
  lifetimeSales: number;
  lifetimeCommission: number;
  smsUsed: number;
  smsQuota: number;
  smsOverageToman: number;
  commissionBps: number;
  ledger: LedgerRow[];
  withdrawals: WithdrawRow[];
};

const KIND: Record<string, string> = {
  sale_sozan: "فروش درگاه سوزان",
  commission: "کمیسیون سوزان",
  sale_external: "فروش روی درگاه شخصی",
  plan: "اشتراک",
  sms: "پیامک اضافه",
  withdraw_hold: "در انتظار برداشت",
  withdraw_paid: "برداشت تأیید شد",
  withdraw_reject: "رد برداشت",
};

const STATUS: Record<string, string> = {
  pending: "در انتظار تأیید",
  paid: "واریز شد",
  rejected: "رد شد",
};

export default function WalletPage() {
  const [wallet, setWallet] = useState<WalletSnap | null>(null);
  const [adminRows, setAdminRows] = useState<WithdrawRow[]>([]);
  const [isAdmin, setIsAdmin] = useState(false);
  const [amount, setAmount] = useState("");
  const [iban, setIban] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load() {
    const [snap, me] = await Promise.all([
      api<WalletSnap>("/wallet"),
      api<{ isAdmin?: boolean }>("/auth/me"),
    ]);
    setWallet(snap);
    setIsAdmin(Boolean(me.isAdmin));
    if (me.isAdmin) {
      const admin = await api<{ withdrawals: WithdrawRow[] }>("/wallet/admin/withdrawals");
      setAdminRows(admin.withdrawals || []);
    }
  }

  useEffect(() => {
    void load().catch((err) => setError(err instanceof Error ? err.message : "خطا"));
  }, []);

  async function requestWithdraw(event: FormEvent) {
    event.preventDefault();
    const nextAmount = parseNonNegativeInt(amount);
    if (nextAmount === null || nextAmount < 1) {
      setError("مبلغ را با عدد بنویس.");
      return;
    }
    const cleanIban = toLatinDigits(iban).replace(/[\s-]/g, "").toUpperCase();
    const fullIban = /^\d{24}$/.test(cleanIban) ? `IR${cleanIban}` : cleanIban;
    if (!/^IR\d{24}$/.test(fullIban)) {
      setError("شبا باید IR و ۲۴ رقم باشد.");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const data = await api<{ wallet: WalletSnap }>("/wallet/withdraw", {
        method: "POST",
        body: JSON.stringify({ amount: nextAmount, iban: fullIban, name }),
      });
      setWallet(data.wallet);
      setAmount("");
      setNotice("درخواست برداشت ثبت شد. بعد از تأیید مدیر واریز می‌شود.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  async function decide(id: string, ok: boolean) {
    setBusy(true);
    setError("");
    try {
      await api(`/wallet/admin/withdrawals/${id}`, {
        method: "POST",
        body: JSON.stringify({ ok }),
      });
      await load();
      setNotice(ok ? "برداشت تأیید شد." : "برداشت رد شد و به کیف برگشت.");
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
          <h1 className="text-lg font-bold">کیف پول</h1>
        </div>
      }
    >
      <div className="h-full space-y-4 overflow-y-auto p-4 [&>*]:mx-auto [&>*]:max-w-3xl">
        {error ? <p className="text-sm text-danger" role="alert">{error}</p> : null}
        {notice ? <p className="text-sm text-signal" role="status">{notice}</p> : null}
        {wallet ? (
          <>
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: "قابل‌برداشت", value: wallet.available, big: true },
                { label: "در انتظار برداشت", value: wallet.pendingWithdraw, big: true },
                { label: "فروش آنلاین", value: wallet.lifetimeSales, big: false },
                { label: "کمیسیون سوزان", value: wallet.lifetimeCommission, big: false },
              ].map((item) => (
                <Card key={item.label} className="min-w-0 p-3">
                  <p className="text-xs text-muted">{item.label}</p>
                  <p
                    className={`mt-1 whitespace-nowrap font-bold ${item.big ? "text-[clamp(0.9rem,4.6vw,1.125rem)]" : "text-[clamp(0.85rem,4vw,1rem)]"}`}
                  >
                    {money(item.value)}
                  </p>
                  <p className="text-xs text-muted">تومان</p>
                </Card>
              ))}
            </div>
            <Card>
              <p className="text-sm leading-7 text-muted">
                فروش دستی وارد کیف نمی‌شود. اگر مرچنت شخصی داشته باشی پول در حساب خودت می‌ماند و اینجا فقط ثبت می‌شود.
                درگاه سوزان {(wallet.commissionBps / 100).toLocaleString("fa-IR")}٪ کمیسیون دارد.
              </p>
              <p className="mt-2 text-sm text-muted">
                پیامک این ماه: {money(wallet.smsUsed)} از {money(wallet.smsQuota)}
                {wallet.smsOverageToman ? ` · بعد از سقف هر پیامک ${money(wallet.smsOverageToman)} تومان` : ""}
              </p>
            </Card>
            <Card>
              <h2 className="font-bold">برداشت با شبا</h2>
              <form className="mt-3 space-y-3" onSubmit={(event) => void requestWithdraw(event)}>
                <Field label="مبلغ به تومان">
                  <Input dir="ltr" inputMode="numeric" value={amount} onChange={(event) => setAmount(event.target.value)} />
                </Field>
                <Field label="شبا">
                  <Input dir="ltr" inputMode="text" autoComplete="off" spellCheck={false} placeholder="IR00 0000 0000 0000 0000 0000 00" value={iban} onChange={(event) => setIban(event.target.value)} />
                </Field>
                <Field label="نام صاحب حساب">
                  <Input value={name} onChange={(event) => setName(event.target.value)} />
                </Field>
                <Button type="submit" disabled={busy || !iban.trim()}>
                  ثبت درخواست برداشت
                </Button>
              </form>
            </Card>
            {isAdmin ? (
              <Card className="space-y-3">
                <h2 className="font-bold">تأیید برداشت‌ها</h2>
                {adminRows.length === 0 ? (
                  <p className="text-sm text-muted">درخواست معلقی نیست.</p>
                ) : (
                  <ul className="space-y-3">
                    {adminRows.map((row) => (
                      <li key={row.id} className="rounded-xl bg-canvas p-3">
                        <p className="text-sm">{row.phone}</p>
                        <p className="font-medium">{money(row.amount)} تومان</p>
                        <p dir="ltr" className="wrap-any text-start text-sm text-muted">{row.iban}</p>
                        <div className="mt-2 flex gap-2">
                          <Button disabled={busy} onClick={() => void decide(row.id, true)}>
                            تأیید
                          </Button>
                          <Button variant="ghost" disabled={busy} onClick={() => void decide(row.id, false)}>
                            رد
                          </Button>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            ) : null}
            <Card>
              <h2 className="font-bold">گردش کیف</h2>
              {(wallet.ledger || []).length === 0 ? (
                <EmptyState title="هنوز گردشی نیست" detail="فروش درگاهی اینجا می‌آید." />
              ) : (
                <ul className="mt-3 space-y-2">
                  {wallet.ledger.map((row) => (
                    <li key={row.id} className="flex items-start justify-between gap-3 text-sm">
                      <div>
                        <p>{KIND[row.kind] || row.kind}</p>
                        {row.note ? <p className="wrap-any text-xs text-muted">{row.note}</p> : null}
                        {row.at ? <p className="text-xs text-muted">{formatWhen(row.at)}</p> : null}
                      </div>
                      <p className={`shrink-0 whitespace-nowrap font-medium ${row.amount < 0 ? "text-danger" : "text-signal"}`}>{money(row.amount)}</p>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            {(wallet.withdrawals || []).length ? (
              <Card>
                <h2 className="font-bold">درخواست‌های برداشت</h2>
                <ul className="mt-3 space-y-2">
                  {wallet.withdrawals.map((row) => (
                    <li key={row.id} className="text-sm">
                      <p>
                        {money(row.amount)} تومان · {STATUS[row.status] || row.status}
                      </p>
                      <p dir="ltr" className="wrap-any text-start text-sm text-muted">{row.iban}</p>
                    </li>
                  ))}
                </ul>
              </Card>
            ) : null}
          </>
        ) : (
          <p className="text-sm text-muted">در حال خواندن کیف…</p>
        )}
      </div>
    </AppShell>
  );
}
