"use client";

import { useEffect } from "react";

export const PUSH_WORKER = "/sozan-push-sw.js";

export function DropStaleWorkers() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    void navigator.serviceWorker.getRegistrations().then((regs) => {
      for (const reg of regs) {
        // the notification worker stays (components/push-toggle.tsx); any older worker goes
        const url = (reg.active || reg.waiting || reg.installing)?.scriptURL || "";
        if (!url.endsWith(PUSH_WORKER)) void reg.unregister();
      }
    });
  }, []);
  return null;
}
