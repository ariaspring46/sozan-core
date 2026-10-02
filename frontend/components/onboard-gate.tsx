"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ApiError, api, getOnboarded, getToken, setOnboarded, timeoutSignal } from "@/lib/api";

const PUBLIC = new Set(["/login", "/onboard", "/", "/about", "/contact", "/terms", "/refund"]);

function isPublicPath(pathname: string) {
  return PUBLIC.has(pathname) || pathname === "/p" || pathname.startsWith("/p/");
}

function instagramReturnQuery(): string {
  if (typeof window === "undefined") return "";
  const src = new URLSearchParams(window.location.search);
  const next = new URLSearchParams();
  for (const key of ["status", "account_id", "username", "id", "instagram", "error", "message"]) {
    const value = src.get(key);
    if (value) next.set(key, value);
  }
  const query = next.toString();
  return query ? `?${query}` : "";
}

export function OnboardGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const publicPath = isPublicPath(pathname);
  const [ok, setOk] = useState(publicPath);
  const [offline, setOffline] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    if (isPublicPath(pathname)) {
      setOk(true);
      return;
    }
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    if (getOnboarded()) setOk(true);
    void api<{ onboarded?: boolean }>("/auth/me", { signal: timeoutSignal(15000) })
      .then((data) => {
        if (!data.onboarded) {
          setOnboarded(false);
          router.replace(`/onboard${instagramReturnQuery()}`);
          return;
        }
        setOnboarded(true);
        setOk(true);
      })
      .catch((err) => {
        // فقط نشست نامعتبر (۴۰۱) یعنی خروج؛ خطای موقت شبکه یا سرور کاربر را بیرون نمی‌اندازد.
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/login");
          return;
        }
        if (!getOnboarded()) setOffline(true);
      });
  }, [pathname, router, retry]);

  if (!ok) {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-3 bg-canvas px-6 text-center">
        {offline ? (
          <>
            <p className="text-sm text-ink">اتصال به سوزان برقرار نشد.</p>
            <button
              type="button"
              className="min-h-11 rounded-xl bg-accentStrong px-4 text-sm font-bold text-onAccent"
              onClick={() => {
                setOffline(false);
                setRetry((value) => value + 1);
              }}
            >
              دوباره
            </button>
          </>
        ) : (
          <p className="text-sm text-muted" role="status">
            در حال بارگذاری…
          </p>
        )}
      </div>
    );
  }
  return <>{children}</>;
}
