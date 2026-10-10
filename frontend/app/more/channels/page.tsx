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
import { Share2 } from "lucide-react";
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

const fa = (value?: number) => Number(value || 0).toLocaleString("fa-IR");

const INSTAGRAM_OAUTH_NOTICE: Record<string, string> = {
  ok: "اینستاگرام وصل شد.",
  exists: "این پیج از قبل وصل شده است. از فهرست انتخابش کن.",
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
      <p className="text-xs text-muted">{label}</p>
      <Input
        dir="ltr"
        value={value}
        placeholder={account.platform === "telegram" ? "@myshop" : "98912…"}
        onChange={(event) => setValue(event.target.value)}
      />
      <Button
        type="button"
        variant="ghost"
        className="w-full text-sm"
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
  const [confirmDelete, setConfirmDelete] = useState("");

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
        const query: Record<string, string> = {};
        params.forEach((value, key) => {
          if (value) query[key] = value;
        });
        const raw = query.instagram || "";
        const status = (query.status || "").toLowerCase();
        const accountId = (query.account_id || query.accountId || "").trim();
        if (raw || status || accountId || query.error || query.username) {
          window.history.replaceState({}, "", window.location.pathname);
        }
        if (accountId || status === "success") {
          const data = await api<{ platforms: Platform[]; accounts: Account[]; voice?: Voice }>(
            "/channels/sendbox/return",
            { method: "POST", body: JSON.stringify({ query }) },
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
        setNotice("این پیج از قبل وصل شده است. انتخابش کن.");
        return;
      }
      if (data.existing?.some((item) => item.bound)) {
        await load();
        setNotice("اینستاگرام از قبل وصل است.");
        return;
      }
      if (data.url) window.location.href = data.url;
      else setError("صفحهٔ ورود اینستاگرام باز نشد. دوباره امتحان کن.");
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
      else if (data.instagram?.ok) setNotice(`${fa(data.instagram.imported)} دایرکت خوانده شد.`);
      else if (data.telegram?.error) setNotice(data.telegram.error);
      else if (data.telegram?.ok) setNotice(`${fa(data.telegram.imported)} پیام تلگرام خوانده شد.`);
      else if (data.scan?.status === "running") setNotice("در حال خواندن صفحه… کالاها به فروش می‌آیند.");
      else if (data.scan?.error) setNotice(data.scan.error);
      else if (data.scan?.productCount) setNotice(`${fa(data.scan.productCount)} کالا از این کانال به فروش اضافه شد.`);
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
          <p className="text-sm text-muted">
            <Link className="tap text-warm" href="/more">
              بیشتر
            </Link>
          </p>
          <h1 className="text-lg font-bold">حساب کانال‌ها</h1>
        </div>
      }
    >
      <div className="h-full space-y-4 overflow-y-auto p-4 [&>*]:mx-auto [&>*]:max-w-3xl">
        <p className="text-sm text-muted">
          کانال را وصل کن تا پیام مشتری‌ها به صندوق بیاید و پست‌ها همان‌جا منتشر شوند.
        </p>
        {error ? <p className="text-sm text-danger" role="alert">{error}</p> : null}
        {notice ? <p className="text-sm text-signal" role="status">{notice}</p> : null}
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
              <p className="text-sm leading-6 text-muted">در حال خواندن پلتفرم‌ها…</p>
            ) : null}
            {spec?.help ? <p className="text-sm leading-7 text-muted">{spec.help}</p> : null}
            {spec?.docs ? (
              <a className="inline-flex min-h-11 items-center text-sm text-warm" href={spec.docs} target="_blank" rel="noreferrer">
                اسناد اتصال {spec.label}
              </a>
            ) : null}
            {spec?.id === "instagram" && spec.sendboxConfigured ? (
              <Button type="button" className="w-full" disabled={busy} onClick={() => void startInstagram()}>
                ورود با اینستاگرام
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
              <p className="text-sm text-warm">ورود با اینستاگرام به‌زودی روشن می‌شود.</p>
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
          <EmptyState icon={Share2} title="حسابی وصل نیست" detail="پلتفرم و مشخصات اتصال را بالا بگذار تا کانال به فروشگاه وصل شود." />
        ) : (
          <ul className="space-y-2">
            {accounts.map((account) => (
              <li key={account.id}>
                <Card className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <p className="wrap-any font-medium">{account.label}</p>
                    <p className="wrap-any text-start text-sm text-muted" dir="ltr">
                      {account.handle}
                    </p>
                    {account.display ? <p className="wrap-any text-sm text-muted">{account.display}</p> : null}
                    <p
                      className={
                        account.needsReconnect
                          ? "text-sm text-warm"
                          : account.verified
                            ? "text-sm text-signal"
                            : account.connected
                              ? "text-sm text-muted"
                              : "text-sm text-warm"
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
                    {account.error ? <p className="wrap-any text-sm text-danger" role="alert">{account.error}</p> : null}
                    <DestEditor account={account} disabled={busy} onAccounts={setAccounts} />
                  </div>
                  <div className="flex flex-wrap gap-2 sm:flex-col">
                    {account.platform === "instagram" && account.needsReconnect ? (
                      <Button disabled={busy} onClick={() => void startInstagram()}>
                        اتصال دوباره
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
                              setNotice(data.error || `${fa(data.imported)} پیام خوانده شد.`);
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
                      className={confirmDelete === account.id ? "border-danger text-danger" : undefined}
                      onClick={() => {
                        if (confirmDelete !== account.id) {
                          setConfirmDelete(account.id);
                          return;
                        }
                        setConfirmDelete("");
                        setBusy(true);
                        void api<{ accounts: Account[] }>(`/channels/${account.id}`, { method: "DELETE" })
                          .then((data) => setAccounts(data.accounts || []))
                          .catch((err) => setError(err instanceof Error ? err.message : "خطا"))
                          .finally(() => setBusy(false));
                      }}
                    >
                      {confirmDelete === account.id ? "تأیید حذف" : "حذف"}
                    </Button>
                    {confirmDelete === account.id ? (
                      <Button variant="ghost" disabled={busy} onClick={() => setConfirmDelete("")}>
                        انصراف
                      </Button>
                    ) : null}
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        )}
        {voice?.summary ? (
          <Card>
            <h2 className="font-bold">لحن یادگرفته</h2>
            <p className="wrap-any mt-1 text-sm">{voice.tone}</p>
            <p className="wrap-any text-sm leading-7 text-muted">{voice.summary}</p>
            {voice.sampleReply ? <p className="wrap-any mt-2 text-sm leading-7">نمونه پاسخ: {voice.sampleReply}</p> : null}
          </Card>
        ) : null}
      </div>
    </AppShell>
  );
}
