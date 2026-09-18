"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { api, getToken } from "@/lib/api";

export function PanelHome() {
  const router = useRouter();
  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    void api<{ onboarded?: boolean }>("/auth/me")
      .then((data) => router.replace(data.onboarded ? "/shop" : "/onboard"))
      .catch(() => router.replace("/login"));
  }, [router]);
  return <p className="p-8 text-muted">در حال انتقال…</p>;
}
