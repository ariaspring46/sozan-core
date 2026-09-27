"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, api, getOnboarded, getToken } from "@/lib/api";

export function PanelHome() {
  const router = useRouter();
  const [offline, setOffline] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    if (getOnboarded()) {
      router.replace("/chat");
      return;
    }
    void api<{ onboarded?: boolean }>("/auth/me")
      .then((data) => router.replace(data.onboarded ? "/chat" : "/onboard"))
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) router.replace("/login");
        else setOffline(true);
      });
  }, [router, retry]);
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-canvas px-6 text-center">
      {offline ? (
        <>
          <p className="text-sm text-ink">اتصال به سوزان برقرار نشد.</p>
          <button
            type="button"
            className="min-h-11 rounded-xl bg-accent px-4 text-sm font-bold text-onAccent"
            onClick={() => {
              setOffline(false);
              setRetry((value) => value + 1);
            }}
          >
            دوباره
          </button>
        </>
      ) : (
        <p className="text-sm text-muted">در حال بارگذاری…</p>
      )}
    </div>
  );
}
