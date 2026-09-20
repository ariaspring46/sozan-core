"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { Field } from "@/components/field";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState } from "@/components/empty-state";
import { api } from "@/lib/api";

type Field = { key: string; label: string; secret: boolean; required: boolean };
type Platform = {
  id: string;
  label: string;
  docs?: string;
  help?: string;
  handleLabel?: string;
  handlePlaceholder?: string;
  fields: Field[];
  oauth?: boolean;
  sendboxConfigured?: boolean;
  hubBot?: boolean;
};
type Voice = { summary: string; tone: string; sampleReply: string };

const INSTAGRAM_OAUTH_NOTICE: Record<string, string> = {
  ok: "اینستاگرام وصل شد.",
  exists: "این پیج از قبل در BoxAPI هست. از لیست انتخابش کن.",
  denied: "اجازهٔ اینستاگرام داده نشد.",
  expired: "نشست ورود اینستاگرام تمام شد. دوباره از پنل وصل کن.",
  config: "اتصال اینستاگرام در سوزان هنوز تنظیم نشده.",
  error: "اتصال اینستاگرام برقرار نشد. دوباره از پنل وصل کن.",
};
type Account = {
  id: string;
  platform: string;
  label: string;
  handle: string;
  display?: string;
  postTarget?: string;
  connected: boolean;
  verified?: boolean;
  error?: string;
  needsReconnect?: boolean;
  voiceReady?: boolean;
};

function DestEditor({
  account,
  disabled,
  onAccounts,
}: {
  account: Account;
  disabled: boolean;
  onAccounts: (rows: Account[]) => void;
}) {
  const [value, setValue] = useState(account.postTarget || "");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    setValue(account.postTarget || "");
  }, [account.postTarget]);
  if (account.platform !== "telegram" && account.platform !== "whatsapp") return null;
  const label = account.platform === "telegram" ? "مقصد پست کانال" : "شماره مقصد ارسال";
  return (
    <div className="mt-2 space-y-2">
      <p className="text-[11px] text-muted">{label}</p>
      <Input
        dir="ltr"
        value={value}
        placeholder={account.platform === "telegram" ? "@myshop" : "98912…"}
        onChange={(event) => setValue(event.target.value)}
      />
      <Button
        type="button"
        variant="ghost"
        className="h-9 min-h-9 w-full text-xs"
        disabled={disabled || saving}
        onClick={() => {
          setSaving(true);
          void api<{ accounts: Account[] }>(`/channels/${account.id}`, {
            method: "PATCH",
            body: JSON.stringify({ postTarget: value }),
          })
            .then((data) => onAccounts(data.accounts || []))
            .finally(() => setSaving(false));
        }}
      >
        ذخیره مقصد
      </Button>
    </div>
  );
}

export default function ChannelsPage() {
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [platform, setPlatform] = useState("instagram");
  const [handle, setHandle] = useState("");
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [samples, setSamples] = useState("");
  const [voice, setVoice] = useState<Voice | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [existing, setExisting] = useState<{ id: string; username: string; bound?: boolean }[]>([]);

  const spec = useMemo(
    () => platforms.find((item) => item.id === platform) || platforms[0],
    [platforms, platform],
  );

  async function load() {
    const data = await api<{ platforms: Platform[]; accounts: Account[]; voice?: Voice }>("/channels");
    setPlatforms(data.platforms || []);
    setAccounts(data.accounts || []);
    if (data.voice) setVoice(data.voice);
    if (data.platforms?.[0] && !data.platforms.some((item) => item.id === platform)) {
      setPlatform(data.platforms[0].id);
    }
  }

  useEffect(() => {
    void (async () => {
      try {
        const params = new URLSearchParams(window.location.search);
        const raw = params.get("instagram");
        const status = (params.get("status") || "").toLowerCase();
        const accountId = (params.get("account_id") || "").trim();
        const username = (params.get("username") || "").trim();
        if (raw || status) window.history.replaceState({}, "", window.location.pathname);
        if (status === "success" && accountId) {
          const data = await api<{ platforms: Platform[]; accounts: Account[]; voice?: Voice }>(
            "/channels/sendbox/claim",
            { method: "POST", body: JSON.stringify({ accountId, handle: username }) },
          );
          setPlatforms(data.platforms || []);
          setAccounts(data.accounts || []);
          if (data.voice) setVoice(data.voice);
          setNotice(INSTAGRAM_OAUTH_NOTICE.ok);
          return;
        }
        if (raw === "exists") {
          try {
            const listed = await api<{ accounts: { id: string; username: string; bound?: boolean }[] }>(
              "/channels/sendbox/accounts",
            );
            setExisting(listed.accounts || []);
          } catch {
            setExisting([]);
          }
        }
        await load();
        if (raw && INSTAGRAM_OAUTH_NOTICE[raw]) setNotice(INSTAGRAM_OAUTH_NOTICE[raw]);
      } catch (err) {
        setError(err instanceof Error ? err.message : "خطا");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  function resetForm(nextPlatform = platform) {
    setHandle("");
    setCredentials({});
    setSamples("");
    setPlatform(nextPlatform);
  }

  async function startInstagram() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const data = await api<{ url: string; existing?: { id: string; username: string; bound?: boolean }[] }>(
        "/channels/instagram/connect",
      );
      if (data.existing?.some((item) => !item.bound)) {
        setExisting(data.existing);
        setNotice("این پیج از قبل در BoxAPI هست. انتخابش کن.");
        return;
      }
      if (data.existing?.some((item) => item.bound)) {
        await load();
        setNotice("اینستاگرام از قبل وصل است.");
        return;
      }
      if (data.url) window.location.href = data.url;
      else setError("نشانی ورود رسمی BoxAPI نیامد.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  const canSubmit = Boolean(
    handle.trim() || (spec?.fields || []).some((field) => (credentials[field.key] || "").trim()),
  );

  async function add(event: FormEvent) {
    event.preventDefault();
    if (!spec) return;
    setBusy(true);
    setError("");
    try {
      const data = await api<{
        platforms: Platform[];
        accounts: Account[];
        voice?: Voice;
        instagram?: { ok?: boolean; imported?: number; error?: string };
        telegram?: { ok?: boolean; imported?: number; error?: string };
        scan?: { status?: string; productCount?: number; error?: string };
        account?: Account;
      }>("/channels", {
        method: "POST",
        body: JSON.stringify({
          platform: spec.id,
          handle,
          credentials,
          samples,
        }),
      });
      setAccounts(data.accounts || []);
      if (data.voice) setVoice(data.voice);
      resetForm(spec.id);
      if (data.account?.error && !data.account.verified) setNotice(data.account.error);
      else if (data.instagram?.error) setNotice(data.instagram.error);
      else if (data.instagram?.ok) setNotice(`${data.instagram.imported || 0} دایرکت خوانده شد.`);
      else if (data.telegram?.error) setNotice(data.telegram.error);
      else if (data.telegram?.ok) setNotice(`${data.telegram.imported || 0} پیام تلگرام خوانده شد.`);
      else if (data.scan?.status === "running") setNotice("در حال خواندن صفحه… کالاها به فروش می‌آیند.");
      else if (data.scan?.error) setNotice(data.scan.error);
      else if (data.scan?.productCount) setNotice(`${data.scan.productCount} کالا از این کانال به فروش اضافه شد.`);
      else if (data.account?.verified) setNotice("اتصال برقرار شد.");
      else setNotice("حساب اضافه شد.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell
      header={
        <div>
          <Link className="text-sm text-warm" href="/more">
            بازگشت
          </Link>
          <h1 className="text-lg font-bold">حساب کانال‌ها</h1>
        </div>
      }
    >
      <div className="h-full space-y-4 overflow-y-auto p-4">
        <p className="text-sm text-muted">
          اینستاگرام را با ورود رسمی BoxAPI وصل کن. اگر بات سوزان روی هاب باشد، برای تلگرام فقط مقصد کانال را بگذار. پست استودیو برای تلگرام به کانالی که بات ادمین آن است می‌رود.
        </p>
        {error ? <p className="text-sm text-danger">{error}</p> : null}
        {notice ? <p className="text-sm text-signal">{notice}</p> : null}
        <Card>
          <form className="space-y-3" onSubmit={(event) => void add(event)}>
            <Field label="پلتفرم">
              <Select value={platform} onChange={(event) => resetForm(event.target.value)}>
                {platforms.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </Select>
            </Field>
            {loading && platforms.length === 0 ? (
              <p className="text-xs leading-6 text-muted">در حال خواندن پلتفرم‌ها…</p>
            ) : null}
            {spec?.help ? <p className="text-xs leading-6 text-muted">{spec.help}</p> : null}
            {spec?.docs ? (
              <a className="inline-block text-xs text-warm" href={spec.docs} target="_blank" rel="noreferrer">
                اسناد اتصال {spec.label}
              </a>
            ) : null}
            {spec?.id === "instagram" && spec.sendboxConfigured ? (
              <Button type="button" disabled={busy} onClick={() => void startInstagram()}>
                ورود رسمی BoxAPI
              </Button>
            ) : null}
            {existing.filter((item) => !item.bound).map((item) => (
              <Button
                key={item.id}
                type="button"
                variant="ghost"
                disabled={busy}
                onClick={() => {
                  setBusy(true);
                  void api<{ accounts: Account[] }>("/channels/sendbox/claim", {
                    method: "POST",
                    body: JSON.stringify({ accountId: item.id, handle: item.username }),
                  })
                    .then((data) => {
                      setAccounts(data.accounts || []);
                      setExisting((prev) => prev.map((row) => (row.id === item.id ? { ...row, bound: true } : row)));
                      setNotice("اینستاگرام وصل شد.");
                    })
                    .catch((err) => setError(err instanceof Error ? err.message : "خطا"))
                    .finally(() => setBusy(false));
                }}
              >
                انتخاب @{item.username || item.id}
              </Button>
            ))}
            {spec?.id === "instagram" && spec.oauth && !spec.sendboxConfigured ? (
              <p className="text-xs text-warm">ورود رسمی BoxAPI وقتی اتصال سوزان در سرور تنظیم شود روشن می‌شود.</p>
            ) : null}
            <Field label={spec?.handleLabel || "شناسه حساب"}>
              <Input
                dir="ltr"
                placeholder={spec?.handlePlaceholder || "@shop"}
                value={handle}
                onChange={(event) => setHandle(event.target.value)}
              />
            </Field>
            {(spec?.fields || []).map((field) => (
              <Field key={field.key} label={field.required ? field.label : `${field.label} (اختیاری)`}>
                <Input
                  dir="ltr"
                  type={field.secret ? "password" : "text"}
                  autoComplete="off"
                  value={credentials[field.key] || ""}
                  onChange={(event) => setCredentials({ ...credentials, [field.key]: event.target.value })}
                />
              </Field>
            ))}
            <Field label="چند پیام به لحن خودت">
              <Textarea
                placeholder="سلام، این مدل موجوده. فردا براتون می‌فرستیم…"
                value={samples}
                onChange={(event) => setSamples(event.target.value)}
              />
            </Field>
            <Button type="submit" disabled={busy || !canSubmit}>
              افزودن حساب
            </Button>
          </form>
        </Card>
        {loading && accounts.length === 0 ? (
          <p className="text-sm text-muted">در حال خواندن حساب‌ها…</p>
        ) : accounts.length === 0 ? (
          <EmptyState title="حسابی وصل نیست" detail="پلتفرم و مشخصات اتصال را بالا بگذار تا کانال به فروشگاه وصل شود." />
        ) : (
          <ul className="space-y-2">
            {accounts.map((account) => (
              <li key={account.id}>
                <Card className="flex items-center justify-between gap-3">
                  <div>
                    <p className="font-medium">{account.label}</p>
                    <p className="text-sm text-muted" dir="ltr">
                      {account.handle}
                    </p>
                    {account.display ? <p className="text-xs text-muted">{account.display}</p> : null}
                    <p
                      className={
                        account.needsReconnect
                          ? "text-xs text-warm"
                          : account.verified
                            ? "text-xs text-signal"
                            : account.connected
                              ? "text-xs text-muted"
                              : "text-xs text-warm"
                      }
                    >
                      {account.needsReconnect
                        ? "باید دوباره وصل شود"
                        : account.verified
                          ? "اتصال تأیید شد"
                          : account.connected
                            ? "وصل است"
                            : "بدون اتصال"}
                      {account.voiceReady ? " · لحن یاد گرفته شد" : ""}
                    </p>
                    {account.error ? <p className="text-xs text-danger">{account.error}</p> : null}
                    <DestEditor account={account} disabled={busy} onAccounts={setAccounts} />
                  </div>
                  <div className="flex flex-col gap-2">
                    {account.platform === "instagram" && account.needsReconnect ? (
                      <Button variant="ghost" disabled={busy} onClick={() => void startInstagram()}>
                        ورود رسمی BoxAPI
                      </Button>
                    ) : null}
                    {account.platform === "telegram" ? (
                      <Button
                        variant="ghost"
                        disabled={busy}
                        onClick={() => {
                          setBusy(true);
                          setNotice("");
                          void api<{ imported?: number; error?: string; ok?: boolean }>(`/channels/${account.id}/sync`, {
                            method: "POST",
                          })
                            .then((data) => {
                              setNotice(data.error || `${data.imported || 0} پیام خوانده شد.`);
                            })
                            .catch((err) => setError(err instanceof Error ? err.message : "خطا"))
                            .finally(() => setBusy(false));
                        }}
                      >
                        خواندن پیام‌ها
                      </Button>
                    ) : null}
                    <Button
                      variant="ghost"
                      disabled={busy}
                      onClick={() => {
                        setBusy(true);
                        void api<{ accounts: Account[] }>(`/channels/${account.id}`, { method: "DELETE" })
                          .then((data) => setAccounts(data.accounts || []))
                          .catch((err) => setError(err instanceof Error ? err.message : "خطا"))
                          .finally(() => setBusy(false));
                      }}
                    >
                      حذف
                    </Button>
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        )}
        {voice?.summary ? (
          <Card>
            <h2 className="font-bold">لحن یادگرفته</h2>
            <p className="mt-1 text-sm">{voice.tone}</p>
            <p className="text-sm text-muted">{voice.summary}</p>
            {voice.sampleReply ? <p className="mt-2 text-sm">نمونه پاسخ: {voice.sampleReply}</p> : null}
          </Card>
        ) : null}
      </div>
    </AppShell>
  );
}
