"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Field } from "@/components/field";
import { LoginCoderScene } from "@/components/login-coder-scene";
import { SozanMark } from "@/components/sozan-mark";
import { api, getToken, setOnboarded } from "@/lib/api";

type Tone = { id: string; label: string };
type Profile = {
  onboarded: boolean;
  firstName: string;
  lastName: string;
  brandName: string;
  brandWork: string;
  toneId: string;
  tones: Tone[];
};

const STEPS = ["نام", "کانال‌ها", "برند", "لحن"] as const;
const DRAFT_KEY = "sozan_onboard_draft";
const CATALOG = [
  { id: "instagram", label: "اینستاگرام" },
  { id: "telegram", label: "تلگرام" },
] as const;

function readLocalDraft(): Record<string, string> {
  try {
    const raw = sessionStorage.getItem(DRAFT_KEY);
    const data = raw ? JSON.parse(raw) : {};
    return data && typeof data === "object" ? data : {};
  } catch {
    return {};
  }
}

function catalogFromDraft(local: Record<string, string>): { platform: string; handle: string } {
  const platform = local.catalogPlatform === "telegram" ? "telegram" : "instagram";
  if (local.catalogHandle) {
    return { platform, handle: local.catalogHandle };
  }
  try {
    const stored = local.handles ? JSON.parse(local.handles) : {};
    if (stored && typeof stored === "object") {
      const ig = String(stored.instagram || "").trim();
      const tg = String(stored.telegram || "").trim();
      if (tg && !ig) return { platform: "telegram", handle: tg };
      if (ig) return { platform: "instagram", handle: ig };
    }
  } catch {
    /* ignore */
  }
  return { platform, handle: "" };
}

export default function OnboardPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [catalogPlatform, setCatalogPlatform] = useState("instagram");
  const [catalogHandle, setCatalogHandle] = useState("");
  const [tones, setTones] = useState<Tone[]>([]);
  const [brandName, setBrandName] = useState("");
  const [brandWork, setBrandWork] = useState("");
  const [toneId, setToneId] = useState("warm");
  const [logo, setLogo] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function persistLocal(next?: Record<string, string>) {
    const payload = {
      firstName,
      lastName,
      brandName,
      brandWork,
      toneId,
      step: String(step),
      catalogPlatform,
      catalogHandle,
      ...next,
    };
    sessionStorage.setItem(DRAFT_KEY, JSON.stringify(payload));
  }

  async function saveDraft(extra?: Record<string, string>) {
    persistLocal(extra);
    await api("/onboard/draft", {
      method: "POST",
      body: JSON.stringify({
        firstName: extra?.firstName ?? firstName,
        lastName: extra?.lastName ?? lastName,
        brandName: extra?.brandName ?? brandName,
        brandWork: extra?.brandWork ?? brandWork,
        toneId: extra?.toneId ?? toneId,
      }),
    });
  }

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    void (async () => {
      try {
        const local = readLocalDraft();
        const data = await api<{ profile: Profile }>("/onboard");
        if (data.profile?.onboarded) {
          router.replace("/shop");
          return;
        }
        setTones(data.profile?.tones || []);
        setToneId(local.toneId || data.profile?.toneId || "warm");
        setFirstName(local.firstName || data.profile?.firstName || "");
        setLastName(local.lastName || data.profile?.lastName || "");
        setBrandName(local.brandName || data.profile?.brandName || "");
        setBrandWork(local.brandWork || data.profile?.brandWork || "");
        const catalog = catalogFromDraft(local);
        setCatalogPlatform(catalog.platform);
        setCatalogHandle(catalog.handle);
        if (local.step && Number(local.step) > 0) {
          setStep(Number(local.step));
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "خطا");
      }
    })();
  }, [router]);

  const brandReady = Boolean(brandName.trim() && brandWork.trim());

  async function finish(event?: FormEvent) {
    event?.preventDefault();
    if (!brandReady) {
      setError("نام برند و کاری که انجام می‌دهید لازم است.");
      setStep(2);
      return;
    }
    setBusy(true);
    setError("");
    const handle = catalogHandle.trim();
    const channels = handle ? [{ platform: catalogPlatform, handle }] : [];
    const body = new FormData();
    body.set("firstName", firstName.trim());
    body.set("lastName", lastName.trim());
    body.set("brandName", brandName.trim());
    body.set("brandWork", brandWork.trim());
    body.set("toneId", toneId);
    body.set("channels", JSON.stringify(channels));
    if (logo) body.set("logo", logo);
    try {
      await api("/onboard/complete", { method: "POST", body });
      sessionStorage.removeItem(DRAFT_KEY);
      setOnboarded(true);
      router.replace("/shop");
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="sozan-lamp relative flex min-h-screen items-end justify-center overflow-hidden sm:items-center">
      <LoginCoderScene />
      <div className="relative z-10 mx-auto w-full max-w-md px-6 pb-[max(1.5rem,env(safe-area-inset-bottom))] pt-40 sm:mt-24 sm:px-6 sm:pb-6 sm:pt-8">
      <Card className="w-full space-y-4 bg-surface/95 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <SozanMark className="h-16 w-16 shrink-0" />
          <div>
            <p className="text-[11px] tracking-[0.22em] text-warm">سوزان</p>
            <p className="text-sm text-muted">ساخت حساب · مرحله {step + 1} از ۴</p>
          </div>
        </div>
        <h1 className="text-2xl font-bold tracking-tight">{STEPS[step]}</h1>
        <div className="flex gap-1">
          {STEPS.map((label, index) => (
            <span
              key={label}
              className={`h-1 flex-1 rounded ${index <= step ? "bg-warm" : "bg-line"}`}
            />
          ))}
        </div>
        {error ? <p className="text-sm text-danger">{error}</p> : null}

        {step === 0 ? (
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              persistLocal({ firstName, lastName, step: "1" });
              void saveDraft();
              setStep(1);
            }}
          >
            <p className="text-sm text-muted">اختیاری است. می‌توانی رد شوی.</p>
            <Field label="نام">
              <Input value={firstName} onChange={(event) => setFirstName(event.target.value)} />
            </Field>
            <Field label="نام خانوادگی">
              <Input value={lastName} onChange={(event) => setLastName(event.target.value)} />
            </Field>
            <div className="flex gap-2">
              <Button type="button" variant="ghost" onClick={() => setStep(1)}>
                رد کردن
              </Button>
              <Button type="submit">ادامه</Button>
            </div>
          </form>
        ) : null}

        {step === 1 ? (
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              persistLocal({ catalogPlatform, catalogHandle, step: "2" });
              setStep(2);
            }}
          >
            <p className="text-sm text-muted">
              فقط یک کانال، و فقط برای خواندن. عکس‌ها و دسته‌بندی همان صفحه برای ساخت سایت استفاده می‌شود. ورود پیام و ارسال پست بعداً از بیشتر ← کانال‌هاست.
            </p>
            <div className="space-y-2">
              {CATALOG.map((item) => (
                <label key={item.id} className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="catalogPlatform"
                    className="h-4 w-4 accent-accent"
                    checked={catalogPlatform === item.id}
                    onChange={() => {
                      setCatalogPlatform(item.id);
                      setCatalogHandle("");
                    }}
                  />
                  {item.label}
                </label>
              ))}
            </div>
            <Field label="شناسه">
              <Input
                dir="ltr"
                placeholder="@shop"
                value={catalogHandle}
                onChange={(event) => setCatalogHandle(event.target.value)}
              />
            </Field>
            <div className="flex gap-2">
              <Button type="button" variant="ghost" onClick={() => setStep(0)}>
                قبلی
              </Button>
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setCatalogHandle("");
                  persistLocal({ catalogHandle: "", step: "2" });
                  setStep(2);
                }}
              >
                رد کردن
              </Button>
              <Button type="submit">ادامه</Button>
            </div>
          </form>
        ) : null}

        {step === 2 ? (
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (!brandReady) {
                setError("نام برند و کاری که انجام می‌دهید لازم است.");
                return;
              }
              setError("");
              persistLocal({ brandName, brandWork, step: "3" });
              void saveDraft();
              setStep(3);
            }}
          >
            <p className="text-sm text-muted">نام برند و شرح کار لازم است. لوگو اختیاری است.</p>
            <Field label="نام برند">
              <Input value={brandName} onChange={(event) => setBrandName(event.target.value)} />
            </Field>
            <Field label="چه کاری انجام می‌دهید">
              <Textarea
                className="min-h-24"
                value={brandWork}
                onChange={(event) => setBrandWork(event.target.value)}
              />
            </Field>
            <Field label="لوگو (اختیاری)">
              <Input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                onChange={(event) => setLogo(event.target.files?.[0] || null)}
              />
            </Field>
            <div className="flex gap-2">
              <Button type="button" variant="ghost" onClick={() => setStep(1)}>
                قبلی
              </Button>
              <Button type="submit" disabled={!brandReady}>
                ادامه
              </Button>
            </div>
          </form>
        ) : null}

        {step === 3 ? (
          <form className="space-y-3" onSubmit={(event) => void finish(event)}>
            <p className="text-sm text-muted">لحن پیام به مشتری. اختیاری است.</p>
            <div className="space-y-2">
              {tones.map((item) => (
                <label key={item.id} className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="tone"
                    className="h-4 w-4 accent-accent"
                    checked={toneId === item.id}
                    onChange={() => setToneId(item.id)}
                  />
                  {item.label}
                </label>
              ))}
            </div>
            <div className="flex gap-2">
              <Button type="button" variant="ghost" onClick={() => setStep(2)}>
                قبلی
              </Button>
              <Button type="button" variant="ghost" disabled={busy} onClick={() => void finish()}>
                رد کردن
              </Button>
              <Button type="submit" disabled={busy}>
                {busy ? "در حال ذخیره…" : "ورود به سوزان"}
              </Button>
            </div>
          </form>
        ) : null}
      </Card>
      </div>
    </main>
  );
}
