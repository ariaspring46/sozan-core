"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, setOnboarded, setToken } from "@/lib/api";
import { toLatinDigits } from "@/lib/digits";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Field } from "@/components/field";
import { LoginCoderScene } from "@/components/login-coder-scene";
import { SozanMark } from "@/components/sozan-mark";

const RESEND_SECONDS = 60;

/** ۰۹۱۲… یا 0912… یا +98912… یا 98912… با فاصله و خط تیره → 09xxxxxxxxx */
function normalizePhone(raw: string): string {
  let value = toLatinDigits(raw).replace(/[\s\-()]/g, "");
  if (value.startsWith("+98")) value = `0${value.slice(3)}`;
  else if (value.startsWith("0098")) value = `0${value.slice(4)}`;
  else if (value.startsWith("98") && value.length === 12) value = `0${value.slice(2)}`;
  else if (value.startsWith("9") && value.length === 10) value = `0${value}`;
  return value;
}

function normalizeCode(raw: string): string {
  return toLatinDigits(raw).replace(/\D/g, "");
}

function phoneHint(raw: string): string {
  const value = normalizePhone(raw);
  if (!value) return "";
  if (!/^\d+$/.test(value)) return "فقط رقم بنویس.";
  if (!value.startsWith("09")) return "شماره موبایل با ۰۹ شروع می‌شود.";
  if (value.length < 11) return `${(11 - value.length).toLocaleString("fa-IR")} رقم دیگر مانده.`;
  if (value.length > 11) return "شماره موبایل ۱۱ رقم است.";
  return "";
}

function faSeconds(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m.toLocaleString("fa-IR")}:${s.toLocaleString("fa-IR").padStart(2, "۰")}`;
}

export default function LoginPage() {
  const router = useRouter();
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [hint, setHint] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [wait, setWait] = useState(0);
  const autoTried = useRef("");

  const cleanPhone = normalizePhone(phone);
  const phoneOk = /^09\d{9}$/.test(cleanPhone);
  const cleanCode = normalizeCode(code);

  useEffect(() => {
    if (wait <= 0) return;
    const timer = window.setTimeout(() => setWait((value) => value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [wait]);

  async function requestCode() {
    setError("");
    setBusy(true);
    try {
      const data = await api<{ ok: boolean; dev_code?: string }>("/auth/otp/send", {
        method: "POST",
        body: JSON.stringify({ phone: cleanPhone }),
      });
      setSent(true);
      setHint(data.dev_code || "");
      setWait(RESEND_SECONDS);
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : "ارسال کد انجام نشد. دوباره امتحان کن.");
    } finally {
      setBusy(false);
    }
  }

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!phoneOk || busy) return;
    await requestCode();
  }

  async function verifyCode(value: string) {
    if (!value || busy) return;
    setError("");
    setBusy(true);
    try {
      const data = await api<{ access_token: string; onboarded?: boolean }>("/auth/otp/verify", {
        method: "POST",
        body: JSON.stringify({ phone: cleanPhone, code: value }),
      });
      setToken(data.access_token);
      setOnboarded(Boolean(data.onboarded));
      router.push(data.onboarded ? "/chat" : "/onboard");
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : "کد درست نبود. دوباره بنویس.");
    } finally {
      setBusy(false);
    }
  }

  async function verify(e: FormEvent) {
    e.preventDefault();
    await verifyCode(cleanCode);
  }

  // وقتی کد کامل شد (مثلاً با پرکردن خودکار از پیامک)، یک بار خودش وارد می‌شود.
  useEffect(() => {
    if (!sent || cleanCode.length !== 6 || autoTried.current === cleanCode) return;
    autoTried.current = cleanCode;
    void verifyCode(cleanCode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cleanCode, sent]);

  const hintText = phoneHint(phone);

  return (
    <main className="sozan-lamp relative flex min-h-screen items-end justify-center overflow-hidden sm:items-center">
      <LoginCoderScene />
      <div className="relative z-10 mx-auto w-full max-w-md px-6 pb-[max(1.5rem,env(safe-area-inset-bottom))] pt-40 sm:mt-24 sm:px-6 sm:pb-6 sm:pt-8">
        <Card className="w-full space-y-5 bg-surface/95 backdrop-blur-md">
          <div className="flex items-center gap-3">
            <SozanMark className="h-20 w-20" />
            <div className="space-y-2">
              <p className="text-[11px] tracking-[0.28em] text-warm">سوزان</p>
              <h1 className="text-2xl font-bold tracking-tight">ورود</h1>
            </div>
          </div>
          <p className="text-sm leading-7 text-muted">فروشگاه را در چت می‌سازی. شماره‌ات را وارد کن تا کد پیامک بیاید.</p>
          {!sent ? (
            <form className="space-y-3" onSubmit={send}>
              <Field label="شماره موبایل">
                <Input
                  dir="ltr"
                  type="tel"
                  inputMode="numeric"
                  autoComplete="tel"
                  maxLength={16}
                  placeholder="09xx xxx xxxx"
                  value={phone}
                  aria-describedby="phone-hint"
                  onChange={(e) => setPhone(e.target.value)}
                />
              </Field>
              <p id="phone-hint" className="min-h-5 text-xs text-muted" aria-live="polite">
                {hintText}
              </p>
              <Button type="submit" className="w-full" disabled={!phoneOk || busy}>
                {busy ? "در حال ارسال…" : "ارسال کد"}
              </Button>
            </form>
          ) : (
            <form className="space-y-3" onSubmit={verify}>
              {hint ? (
                <p className="rounded-full border border-line bg-canvas px-3 py-1 text-center text-xs text-muted">
                  کد آزمایشی {hint}
                </p>
              ) : null}
              <p className="text-sm text-muted">
                کد پیامک به <bdi dir="ltr">{cleanPhone}</bdi> فرستاده شد.
              </p>
              <Field label="کد پیامک">
                <Input
                  dir="ltr"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={8}
                  className="text-center tracking-[0.4em]"
                  value={code}
                  autoFocus
                  onChange={(e) => setCode(e.target.value)}
                />
              </Field>
              <Button type="submit" className="w-full" disabled={!cleanCode || busy}>
                {busy ? "در حال بررسی…" : "ورود"}
              </Button>
              <div className="flex items-center justify-between gap-2 text-sm">
                <button
                  type="button"
                  className="min-h-11 px-1 text-warm"
                  onClick={() => {
                    setSent(false);
                    setCode("");
                    setHint("");
                    setError("");
                    setWait(0);
                    autoTried.current = "";
                  }}
                >
                  ویرایش شماره
                </button>
                {wait > 0 ? (
                  <span className="text-muted" aria-live="polite">
                    ارسال دوباره تا {faSeconds(wait)}
                  </span>
                ) : (
                  <button
                    type="button"
                    className="min-h-11 px-1 text-warm disabled:text-muted"
                    disabled={busy}
                    onClick={() => {
                      setCode("");
                      autoTried.current = "";
                      void requestCode();
                    }}
                  >
                    ارسال دوبارهٔ کد
                  </button>
                )}
              </div>
            </form>
          )}
          {error ? (
            <p className="text-sm text-danger" role="alert">
              {error}
            </p>
          ) : null}
        </Card>
      </div>
    </main>
  );
}
