"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { PUSH_WORKER } from "@/components/drop-stale-workers";
import { api } from "@/lib/api";

type State = "loading" | "unsupported" | "install" | "denied" | "off" | "on";

function keyBytes(base64: string): ArrayBuffer {
  const padded = (base64 + "=".repeat((4 - (base64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(padded);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out.buffer;
}

function isIos(): boolean {
  return /iphone|ipad|ipod/i.test(navigator.userAgent);
}

function standalone(): boolean {
  return window.matchMedia("(display-mode: standalone)").matches || (navigator as Navigator & { standalone?: boolean }).standalone === true;
}

async function currentSubscription(): Promise<PushSubscription | null> {
  const reg = await navigator.serviceWorker.getRegistration("/");
  if (!reg || !(reg.active || reg.waiting || reg.installing)?.scriptURL.endsWith(PUSH_WORKER)) return null;
  return reg.pushManager.getSubscription();
}

/** روشن و خاموش کردن اعلان سوزان روی همین گوشی یا مرورگر (سفارش تازه، رسید، یادآوری‌ها). */
export function PushToggle({ compact = false }: { compact?: boolean }) {
  const [state, setState] = useState<State>("loading");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  useEffect(() => {
    if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
      setState(isIos() && !standalone() ? "install" : "unsupported");
      return;
    }
    if (Notification.permission === "denied") {
      setState("denied");
      return;
    }
    void currentSubscription()
      .then((sub) => setState(sub ? "on" : "off"))
      .catch(() => setState("off"));
  }, []);

  async function turnOn() {
    setBusy(true);
    setNote("");
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setState(permission === "denied" ? "denied" : "off");
        return;
      }
      const { publicKey } = await api<{ publicKey: string }>("/events/push");
      const reg = await navigator.serviceWorker.register(PUSH_WORKER, { scope: "/" });
      await navigator.serviceWorker.ready;
      const sub =
        (await reg.pushManager.getSubscription()) ||
        (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(publicKey) }));
      await api("/events/push/subscribe", { method: "POST", body: JSON.stringify(sub.toJSON()) });
      const sent = await api<{ sent: number }>("/events/push/test", { method: "POST" });
      setState("on");
      setNote(sent.sent ? "یک اعلان آزمایشی فرستادیم." : "روشن شد؛ اعلان آزمایشی نرسید، یک بار صفحه را تازه کن.");
    } catch (err) {
      setNote(err instanceof Error ? err.message : "روشن نشد.");
    } finally {
      setBusy(false);
    }
  }

  async function turnOff() {
    setBusy(true);
    setNote("");
    try {
      const sub = await currentSubscription();
      if (sub) {
        await api("/events/push/unsubscribe", { method: "POST", body: JSON.stringify({ endpoint: sub.endpoint }) });
        await sub.unsubscribe();
      }
      setState("off");
    } catch (err) {
      setNote(err instanceof Error ? err.message : "خاموش نشد.");
    } finally {
      setBusy(false);
    }
  }

  if (state === "loading" || (compact && state === "on") || (compact && state === "unsupported")) return null;

  const text: Record<Exclude<State, "loading">, string> = {
    on: "سفارش تازه، رسید کارت‌به‌کارت و یادآوری‌ها روی همین دستگاه خبر داده می‌شوند، حتی وقتی سوزان باز نیست.",
    off: "وقتی سوزان باز نیست هم از سفارش تازه و رسید کارت‌به‌کارت باخبر شو.",
    denied: "اعلان برای این سایت در مرورگر بسته است. از تنظیمات مرورگر، اعلان app.sozan-core.ir را مجاز کن.",
    install: "در آیفون، اول سوزان را به صفحهٔ اصلی اضافه کن (دکمهٔ اشتراک‌گذاری ← Add to Home Screen) و از همان آیکون باز کن.",
    unsupported: "این مرورگر اعلان ندارد. با کروم یا فایرفاکس باز کن.",
  };

  return (
    <section aria-labelledby="push-title" className="rounded-2xl bg-canvas p-4 shadow-card">
      <div className="flex items-center justify-between gap-3">
        <p id="push-title" className="font-bold">
          اعلان روی گوشی
        </p>
        {state === "on" ? (
          <Button type="button" variant="ghost" disabled={busy} onClick={() => void turnOff()}>
            خاموش کن
          </Button>
        ) : state === "off" ? (
          <Button type="button" disabled={busy} onClick={() => void turnOn()}>
            {busy ? "…" : "روشن کن"}
          </Button>
        ) : null}
      </div>
      <p className="mt-1 text-sm leading-6 text-muted">{text[state]}</p>
      {note ? <p className="mt-1 text-xs text-muted">{note}</p> : null}
    </section>
  );
}
