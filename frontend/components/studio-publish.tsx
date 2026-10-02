"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

export type StudioAttachment = { kind: string; name: string; source?: string };
export type StudioCaptions = { instagram?: string; telegram?: string; whatsapp?: string };
export type PublishTarget = {
  platform: string;
  label: string;
  handle?: string;
  ready: boolean;
  hint: string;
};
export type PublishPayload = {
  campaignId?: string;
  messageId?: string;
  platform: string;
  caption: string;
  mediaName: string;
  mediaKind: string;
  force?: boolean;
  recipientId?: string;
};

type AudienceRow = {
  id: string;
  sender: string;
  recipientId: string;
  lastText: string;
  pending?: boolean;
};

const CHANNELS = [
  { platform: "instagram", label: "اینستاگرام", limit: 2200 },
  { platform: "telegram", label: "تلگرام", limit: 1024 },
  { platform: "whatsapp", label: "واتساپ", limit: 1024 },
] as const;

function pickMedia(attachments: StudioAttachment[], platform: string): StudioAttachment {
  const sourceOf = (item: StudioAttachment) => item.source || item.name || "";
  const image = attachments.find((item) => item.kind === "image");
  const video = attachments.find((item) => item.kind === "video");
  if (platform === "telegram") {
    return (
      attachments.find((item) => /tg-wide|tg-video/.test(sourceOf(item))) ||
      image ||
      video ||
      attachments[0]
    );
  }
  if (platform === "instagram" && image) return image;
  return image || video || attachments[0];
}

export function StudioPublishCard({
  campaignId,
  messageId,
  attachments,
  captions,
  published,
  targets,
  onPublish,
  onRegenerate,
  onSaveCaptions,
}: {
  campaignId?: string;
  messageId?: string;
  attachments: StudioAttachment[];
  captions?: StudioCaptions;
  published?: Record<string, number>;
  targets: PublishTarget[];
  onPublish: (payload: PublishPayload) => Promise<{ skipped?: boolean; message?: string } | void>;
  onRegenerate?: (part: "image" | "caption", file?: File) => Promise<void>;
  onSaveCaptions?: (captions: StudioCaptions) => void | Promise<void>;
}) {
  const [drafts, setDrafts] = useState<StudioCaptions>({
    instagram: captions?.instagram || "",
    telegram: captions?.telegram || "",
    whatsapp: captions?.whatsapp || "",
  });
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [confirmFor, setConfirmFor] = useState("");
  const [savedHint, setSavedHint] = useState(false);
  const [mediaByChannel, setMediaByChannel] = useState<Record<string, string>>({});
  const [sentAt, setSentAt] = useState<Record<string, number>>(published || {});
  const [audienceQ, setAudienceQ] = useState("");
  const [audience, setAudience] = useState<AudienceRow[]>([]);
  const [picked, setPicked] = useState<AudienceRow | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const primed = useRef(false);

  useEffect(() => {
    setSentAt((prev) => ({ ...prev, ...(published || {}) }));
  }, [published]);

  useEffect(() => {
    setDrafts({
      instagram: captions?.instagram || "",
      telegram: captions?.telegram || "",
      whatsapp: captions?.whatsapp || "",
    });
  }, [captions?.instagram, captions?.telegram, captions?.whatsapp]);

  useEffect(() => {
    if (!onSaveCaptions || !messageId) return;
    if (!primed.current) {
      primed.current = true;
      return;
    }
    const timer = window.setTimeout(() => {
      void Promise.resolve(onSaveCaptions(drafts))
        .then(() => {
          setSavedHint(true);
          window.setTimeout(() => setSavedHint(false), 1200);
        })
        .catch(() => {
          setError("کپشن ذخیره نشد");
        });
    }, 800);
    return () => window.clearTimeout(timer);
  }, [drafts.instagram, drafts.telegram, drafts.whatsapp, messageId, onSaveCaptions]);

  const igReady = Boolean(targets.find((row) => row.platform === "instagram" && row.ready));

  useEffect(() => {
    if (!igReady) return;
    const timer = window.setTimeout(() => {
      const query = audienceQ.trim() ? `?q=${encodeURIComponent(audienceQ.trim())}` : "";
      void api<{ rows?: AudienceRow[] }>(`/studio/audience${query}`)
        .then((data) => setAudience(data.rows || []))
        .catch(() => setAudience([]));
    }, audienceQ ? 280 : 0);
    return () => window.clearTimeout(timer);
  }, [igReady, audienceQ]);

  const byPlatform = useMemo(() => {
    const map: Record<string, PublishTarget> = {};
    for (const row of targets) map[row.platform] = row;
    return map;
  }, [targets]);

  if (!attachments.length) return null;

  async function send(platform: (typeof CHANNELS)[number]["platform"], force = false) {
    const spec = CHANNELS.find((item) => item.platform === platform);
    if (!spec) return;
    if (platform === "instagram" && !picked?.recipientId) {
      setError("مخاطب دایرکت را انتخاب کن.");
      return;
    }
    const sentAlready = Boolean(sentAt[platform] || published?.[platform]);
    if (sentAlready && !force) {
      setConfirmFor(platform);
      return;
    }
    const chosenName = mediaByChannel[platform] || pickMedia(attachments, platform).name;
    const chosen = attachments.find((item) => item.name === chosenName) || pickMedia(attachments, platform);
    setBusy(platform);
    setError("");
    setNotice("");
    setConfirmFor("");
    try {
      const result = await onPublish({
        campaignId,
        messageId,
        platform,
        caption: (drafts[platform] || "").slice(0, spec.limit),
        mediaName: chosen.name,
        mediaKind: chosen.kind,
        force: sentAlready,
        recipientId: platform === "instagram" ? picked?.recipientId : undefined,
      });
      if (result?.skipped) {
        setNotice(result.message || "به‌تازگی ارسال شده؛ برای ارسال دوباره تأیید کن");
        setConfirmFor(platform);
      } else {
        setSentAt((prev) => ({ ...prev, [platform]: Date.now() / 1000 }));
        setNotice(`به ${spec.label} ارسال شد.`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "ارسال نشد");
    } finally {
      setBusy("");
    }
  }

  async function regen(part: "image" | "caption", file?: File) {
    if (!onRegenerate) return;
    setBusy(part);
    setError("");
    try {
      await onRegenerate(part, file);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ساخت دوباره نشد");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="mt-3 space-y-3 rounded-2xl border border-line/70 bg-canvas/70 p-3">
      <p className="text-sm font-medium text-warm">ارسال به شبکه‌های ثبت‌شده</p>
      {onRegenerate ? (
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="ghost"
            className="shrink-0 whitespace-nowrap text-sm"
            disabled={Boolean(busy)}
            onClick={() => void regen("caption")}
          >
            {busy === "caption" ? "در حال نوشتن…" : "ساخت دوباره کپشن"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            className="shrink-0 whitespace-nowrap text-sm"
            disabled={Boolean(busy)}
            onClick={() => void regen("image")}
          >
            {busy === "image" ? "در حال ساخت…" : "ساخت دوباره عکس"}
          </Button>
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            accept="image/png,image/jpeg,image/webp"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) void regen("image", file);
            }}
          />
          <Button
            type="button"
            variant="ghost"
            className="shrink-0 whitespace-nowrap text-sm"
            disabled={Boolean(busy)}
            onClick={() => fileRef.current?.click()}
          >
            ویرایش عکس
          </Button>
        </div>
      ) : null}
      {CHANNELS.map((channel) => {
        const target = byPlatform[channel.platform];
        const key = channel.platform as keyof StudioCaptions;
        const selected = mediaByChannel[channel.platform] || pickMedia(attachments, channel.platform).name;
        const sent = Boolean(sentAt[channel.platform] || published?.[channel.platform]);
        return (
          <div key={channel.platform} className="space-y-2">
            <label className="block text-sm text-muted" htmlFor={`caption-${channel.platform}`}>{`کپشن ${channel.label}`}</label>
            <textarea
              id={`caption-${channel.platform}`}
              className="wrap-any min-h-24 w-full rounded-xl border border-field bg-paper px-3 py-2 text-sm leading-7 outline-none focus:border-accent"
              value={drafts[key] || ""}
              maxLength={channel.limit}
              onChange={(event) => setDrafts({ ...drafts, [key]: event.target.value })}
            />
            {attachments.length > 1 ? (
              <div className="flex flex-wrap gap-2" role="group" aria-label="رسانهٔ ارسال">
                {attachments.map((item) => (
                  <button
                    key={item.name}
                    type="button"
                    className={`tap rounded-full border px-4 py-1.5 text-[13px] ${selected === item.name ? "border-accent bg-accent/15 font-bold text-warm" : "border-line text-muted"}`}
                    aria-pressed={selected === item.name}
                    onClick={() => setMediaByChannel({ ...mediaByChannel, [channel.platform]: item.name })}
                  >
                    {item.kind === "video" ? "ویدیو" : "تصویر"}
                  </button>
                ))}
              </div>
            ) : null}
            {channel.platform === "instagram" && target?.ready ? (
              <div className="space-y-2 rounded-xl border border-line/70 bg-paper/70 p-2">
                <label className="block text-sm text-muted" htmlFor="audience-search">مخاطب دایرکت</label>
                <input
                  id="audience-search"
                  className="min-h-11 w-full rounded-lg border border-field bg-canvas px-3 text-[16px] outline-none focus:border-accent"
                  value={audienceQ}
                  onChange={(event) => setAudienceQ(event.target.value)}
                  placeholder="جستجو در اخیر و پیش‌نویس"
                />
                {picked ? (
                  <p className="text-sm text-signal">
                    انتخاب‌شده: {picked.sender}
                    {picked.pending ? " · پیش‌نویس" : ""}
                  </p>
                ) : (
                  <p className="text-sm text-muted">از اخیر یک نفر را انتخاب کن؛ بدون مخاطب ارسال نمی‌شود.</p>
                )}
                <div className="max-h-48 space-y-1 overflow-y-auto overscroll-contain">
                  {audience.length === 0 ? (
                    <p className="text-sm text-muted">در صندوق مخاطب اینستاگرام نیست. اول پیام‌های تازه را در صندوق بگیر.</p>
                  ) : (
                    audience.map((row) => (
                      <button
                        key={row.id}
                        type="button"
                        className={`block min-h-11 w-full rounded-lg px-3 py-1.5 text-start text-xs ${
                          picked?.recipientId === row.recipientId ? "bg-signal/15 text-warm" : "text-muted hover:bg-canvas"
                        }`}
                        onClick={() => setPicked(row)}
                      >
                        <span className="wrap-any text-sm font-medium text-ink">{row.sender}</span>
                        {row.pending ? <span className="ms-1 text-warm">پیش‌نویس</span> : null}
                        {row.lastText ? <span className="mt-0.5 block truncate">{row.lastText}</span> : null}
                      </button>
                    ))
                  )}
                </div>
              </div>
            ) : null}
            <Button
              type="button"
              variant={sent ? "primary" : "ghost"}
              className={
                sent
                  ? "wrap-any w-full text-sm bg-signal text-onAccent hover:bg-signal"
                  : "wrap-any w-full text-sm"
              }
              disabled={Boolean(busy) || !target?.ready || (channel.platform === "instagram" && !picked?.recipientId)}
              onClick={() => void send(channel.platform, confirmFor === channel.platform)}
            >
              {busy === channel.platform
                ? "در حال ارسال…"
                : confirmFor === channel.platform
                  ? "مطمئنی؟ دوباره بفرست"
                  : sent
                    ? "ارسال دوباره"
                    : channel.platform === "telegram"
                      ? "ارسال به کانال تلگرام"
                      : channel.platform === "instagram"
                        ? picked
                          ? `ارسال دایرکت به ${picked.sender}`
                          : "ارسال دایرکت"
                        : `ارسال به ${channel.label}`}
            </Button>
            {!target ? <p className="text-sm text-muted">حساب {channel.label} وصل نیست.</p> : null}
            {target && !target.ready ? <p className="text-sm text-warm">{target.hint}</p> : null}
          </div>
        );
      })}
      {savedHint ? <p className="text-sm text-muted" role="status">ذخیره شد</p> : null}
      {notice ? <p className="text-sm text-signal" role="status">{notice}</p> : null}
      {error ? <p className="text-sm text-danger" role="alert">{error}</p> : null}
      <Link className="inline-flex min-h-11 items-center text-sm text-warm" href="/more/channels">
        تنظیم حساب کانال‌ها
      </Link>
    </div>
  );
}
