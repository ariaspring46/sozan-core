"use client";

import { AppShell } from "@/components/app-shell";
import { StudioLibrary } from "@/components/studio-library";
import { StudioNav } from "@/components/studio-nav";

export default function StudioPage() {
  return (
    <AppShell
      header={
        <div>
          <p className="text-sm text-muted">استودیو</p>
          <h1 className="text-lg font-bold">رسانه‌های ساخته‌شده</h1>
        </div>
      }
    >
      <div className="flex h-full flex-col">
        <div className="px-4 pt-3">
          <StudioNav current="studio" />
        </div>
        <div className="min-h-0 flex-1">
          <StudioLibrary />
        </div>
      </div>
    </AppShell>
  );
}
