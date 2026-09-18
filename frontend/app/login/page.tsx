"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api, setOnboarded, setToken } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Field } from "@/components/field";
import { LoginCoderScene } from "@/components/login-coder-scene";
import { SozanMark } from "@/components/sozan-mark";

export default function LoginPage() {
  const router = useRouter();
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [hint, setHint] = useState("");
  const [error, setError] = useState("");

  async function send(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const data = await api<{ ok: boolean; dev_code?: string }>("/auth/otp/send", {
        method: "POST",
        body: JSON.stringify({ phone }),
      });
      setSent(true);
      setHint(data.dev_code || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    }
  }

  async function verify(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const data = await api<{ access_token: string; onboarded?: boolean }>("/auth/otp/verify", {
        method: "POST",
        body: JSON.stringify({ phone, code }),
      });
      setToken(data.access_token);
      setOnboarded(Boolean(data.onboarded));
      router.push(data.onboarded ? "/shop" : "/onboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    }
  }

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
                  inputMode="numeric"
                  autoComplete="tel"
                  placeholder="0912…"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                />
              </Field>
              <Button type="submit" className="w-full" disabled={!phone.trim()}>
                ارسال کد
              </Button>
            </form>
          ) : (
            <form className="space-y-3" onSubmit={verify}>
              {hint ? (
                <p className="rounded-full border border-line bg-canvas px-3 py-1 text-center text-xs text-muted">
                  کد آزمایشی {hint}
                </p>
              ) : null}
              <p className="text-sm text-muted">کد پیامک به {phone} فرستاده شد.</p>
              <button
                type="button"
                className="text-sm text-warm"
                onClick={() => {
                  setSent(false);
                  setCode("");
                  setHint("");
                  setError("");
                }}
              >
                ویرایش شماره
              </button>
              <Field label="کد">
                <Input dir="ltr" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} />
              </Field>
              <Button type="submit" className="w-full">
                ورود
              </Button>
            </form>
          )}
          {error ? <p className="text-sm text-danger">{error}</p> : null}
        </Card>
      </div>
    </main>
  );
}
