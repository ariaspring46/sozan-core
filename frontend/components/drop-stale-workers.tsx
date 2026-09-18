"use client";

import { useEffect } from "react";

export function DropStaleWorkers() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    void navigator.serviceWorker.getRegistrations().then((regs) => {
      for (const reg of regs) void reg.unregister();
    });
  }, []);
  return null;
}
