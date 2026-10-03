"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { Check, ImagePlus, PenLine, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

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

/** «تصویر» به‌تنهایی کمک نمی‌کند: فروشنده باید بداند کدام خروجی پست، استوری یا عریض است. */
function mediaLabel(item: StudioAttachment): string {
  const blob = `${item.source || ""} ${item.name || ""}`;
  if (item.kind === "video") return /reel/.test(blob) ? "ویدیوی ریلز" : "ویدیو";
  if (/story/.test(blob)) return "استوری";
  if (/wide/.test(blob)) return "عکس عریض";
  if (/tg-post/.test(blob)) return "پست کانال";
  if (/feed/.test(blob)) return "پست اینستاگرام";
  return "تصویر";
}

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
  const [tab, setTab] = useState<string>(() => (targets.find((row) => row.ready)?.platform as string) || "instagram");
  const [savedHint, setSavedHint] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [audienceError, setAudienceError] = useState(false);
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
    // متنی که همین حالا از سرور آمده دوباره ذخیره نمی‌شود (هر بار تازه‌شدن گفتگو یک درخواست بی‌خود بود).
    if (
      (drafts.instagram || "") === (captions?.instagram || "") &&
      (drafts.telegram || "") === (captions?.telegram || "") &&
      (drafts.whatsapp || "") === (captions?.whatsapp || "")
    ) {
      return;
    }
    const timer = window.setTimeout(() => {
      void Promise.resolve(onSaveCaptions(drafts))
        .then(() => {
          setSaveError("");
          setSavedHint(true);
          window.setTimeout(() => setSavedHint(false), 2500);
        })
        .catch(() => {
          setSaveError("کپشن ذخیره نشد. دوباره امتحان کن.");
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
        .then((data) => {
          setAudience(data.rows || []);
          setAudienceError(false);
        })
        .catch(() => {
          setAudience([]);
          setAudienceError(true);
        });
    }, audienceQ ? 280 : 0);
    return () => window.clearTimeout(timer);
  }, [igReady, audienceQ]);

  const byPlatform = useMemo(() => {
    const map: Record<string, PublishTarget> = {};
    for (const row of targets) map[row.platform] = row;
    return map;
  }, [targets]);

  // ارسال به کانال یا مشتری برگشت‌پذیر نیست: لمس اول فقط آماده می‌کند، لمس دوم (تا ۶ ثانیه) می‌فرستد.
  useEffect(() => {
    if (!confirmFor) return;
    const timer = window.setTimeout(() => setConfirmFor(""), 6000);
    return () => window.clearTimeout(timer);
  }, [confirmFor]);

  if (!attachments.length) return null;

  async function send(platform: (typeof CHANNELS)[number]["platform"], force = false) {
    const spec = CHANNELS.find((item) => item.platform === platform);
    if (!spec) return;
    if (platform === "instagram" && !picked?.recipientId) {
      setError("مخاطب دایرکت را انتخاب کن.");
      return;
    }
    const sentAlready = Boolean(sentAt[platform] || published?.[platform]);
    if (!force) {
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

  const channel = CHANNELS.find((item) => item.platform === tab) || CHANNELS[0];
  const target = byPlatform[channel.platform];
  const key = channel.platform as keyof StudioCaptions;
  const selected = mediaByChannel[channel.platform] || pickMedia(attachments, channel.platform).name;
  const sent = Boolean(sentAt[channel.platform] || published?.[channel.platform]);
  const text = drafts[key] || "";
  const sendLabel =
    busy === channel.platform
      ? "در حال ارسال…"
      : confirmFor === channel.platform
        ? sent
          ? "مطمئنی؟ دوباره بفرست"
          : `مطمئنی؟ بفرست به ${channel.platform === "instagram" && picked ? picked.sender : channel.label}`
        : sent
          ? "ارسال دوباره"
          : channel.platform === "telegram"
            ? "ارسال به کانال تلگرام"
            : channel.platform === "instagram"
              ? picked
                ? `ارسال دایرکت به ${picked.sender}`
                : "ارسال دایرکت"
              : `ارسال به ${channel.label}`;

  return (
    <div className="mt-3 overflow-hidden rounded-2xl border border-line/70 bg-canvas">
      <div role="tablist" aria-label="کانال ارسال" className="flex gap-1 border-b border-line/60 bg-paper p-1.5">
        {CHANNELS.map((item) => {
          const row = byPlatform[item.platform];
          const done = Boolean(sentAt[item.platform] || published?.[item.platform]);
          const on = item.platform === channel.platform;
          return (
            <button
              key={item.platform}
              type="button"
              role="tab"
              id={`tab-${item.platform}`}
              aria-selected={on}
              aria-controls="studio-channel-panel"
              onClick={() => {
                setTab(item.platform);
                setConfirmFor("");
              }}
              className={cn(
                "flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-xl px-2 text-[13px]",
                on ? "bg-canvas font-bold text-ink shadow-sm" : "text-muted hover:bg-canvas/60",
              )}
            >
              <span
                aria-hidden
                className={cn("h-2 w-2 rounded-full", done ? "bg-signal" : row?.ready ? "bg-accent" : "bg-line")}
              />
              {item.label}
              {done ? <Check size={13} aria-hidden className="text-signal" /> : null}
            </button>
          );
        })}
      </div>
      <div role="tabpanel" id="studio-channel-panel" aria-labelledby={`tab-${channel.platform}`} className="space-y-2.5 p-3">
        <label className="block text-sm text-muted" htmlFor={`caption-${channel.platform}`}>{`کپشن ${channel.label}`}</label>
        <textarea
          id={`caption-${channel.platform}`}
          className="wrap-any min-h-32 w-full rounded-xl border border-field bg-paper px-3 py-2.5 text-[15px] leading-[1.9] outline-none focus:border-accent"
          value={text}
          maxLength={channel.limit}
          onChange={(event) => setDrafts({ ...drafts, [key]: event.target.value })}
        />
        <p className={`text-end text-xs ${text.length >= channel.limit - 20 ? "text-danger" : "text-muted"}`}>
          {text.length.toLocaleString("fa-IR")} از {channel.limit.toLocaleString("fa-IR")}
        </p>
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
                {mediaLabel(item)}
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
              {audienceError ? (
                <p className="text-sm text-danger" role="alert">
                  فهرست مخاطب‌ها خوانده نشد. جستجو را دوباره بزن.
                </p>
              ) : audience.length === 0 ? (
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
          className={cn("wrap-any w-full text-sm", sent ? "bg-signal text-onAccent hover:bg-signal" : confirmFor === channel.platform ? "border-accent bg-accent/10 text-warm" : "")}
          disabled={Boolean(busy) || !target?.ready || (channel.platform === "instagram" && !picked?.recipientId)}
          onClick={() => void send(channel.platform, confirmFor === channel.platform)}
        >
          {sendLabel}
        </Button>
        {!target ? <p className="text-sm text-muted">حساب {channel.label} وصل نیست.</p> : null}
        {target && !target.ready ? <p className="text-sm text-warm">{target.hint}</p> : null}
      </div>
      {onRegenerate ? (
        <div className="grid grid-cols-3 gap-1.5 border-t border-line/60 bg-paper/60 p-2">
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
          <button
            type="button"
            className="inline-flex min-h-14 flex-col items-center justify-center gap-1 rounded-xl text-[12px] text-muted hover:bg-canvas disabled:opacity-50"
            disabled={Boolean(busy)}
            onClick={() => void regen("caption")}
          >
            <PenLine size={17} aria-hidden />
            {busy === "caption" ? "در حال نوشتن…" : "کپشن تازه"}
            <span className="sr-only">ساخت دوباره کپشن</span>
          </button>
          <button
            type="button"
            className="inline-flex min-h-14 flex-col items-center justify-center gap-1 rounded-xl text-[12px] text-muted hover:bg-canvas disabled:opacity-50"
            disabled={Boolean(busy)}
            onClick={() => void regen("image")}
          >
            <RefreshCw size={17} aria-hidden />
            {busy === "image" ? "در حال ساخت…" : "عکس تازه"}
            <span className="sr-only">ساخت دوباره عکس</span>
          </button>
          <button
            type="button"
            className="inline-flex min-h-14 flex-col items-center justify-center gap-1 rounded-xl text-[12px] text-muted hover:bg-canvas disabled:opacity-50"
            disabled={Boolean(busy)}
            onClick={() => fileRef.current?.click()}
          >
            <ImagePlus size={17} aria-hidden />
            عکس خودم
            <span className="sr-only">ویرایش عکس</span>
          </button>
        </div>
      ) : null}
      <div className="space-y-1 px-3 pb-2">
        {savedHint ? <p className="text-sm text-muted" role="status">ذخیره شد</p> : null}
        {notice ? <p className="text-sm text-signal" role="status">{notice}</p> : null}
        {saveError ? <p className="text-sm text-danger" role="alert">{saveError}</p> : null}
        {error ? <p className="text-sm text-danger" role="alert">{error}</p> : null}
        <Link className="inline-flex min-h-11 items-center text-sm text-warm" href="/more/channels">
          تنظیم حساب کانال‌ها
        </Link>
      </div>
    </div>
  );
}
