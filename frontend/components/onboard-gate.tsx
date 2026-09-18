"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api, getOnboarded, getToken, setOnboarded } from "@/lib/api";

const PUBLIC = new Set(["/login", "/onboard", "/"]);

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
    void api<{ onboarded?: boolean }>("/auth/me")
      .then((data) => {
        if (!data.onboarded) {
          setOnboarded(false);
          router.replace(`/onboard${instagramReturnQuery()}`);
          return;
        }
        setOnboarded(true);
        setOk(true);
      })
      .catch(() => {
        router.replace("/login");
      });
  }, [pathname, router]);

  if (!ok) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas">
        <p className="text-sm text-muted">در حال بارگذاری…</p>
      </div>
    );
  }
  return <>{children}</>;
}
