"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, Clock, Copy, ExternalLink, Globe, RefreshCw, TriangleAlert } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { personalDomainValue, shopHostLabel, shopPublicUrl, type ShopState } from "@/components/domain-menu";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

type ShopPayload = { shop: ShopState };

/** Suffixes whose registrable name has three labels: shop.example.co.ir → record name «shop». */
const SECOND_LEVEL = /\.(co|ac|org|net|gov|id|sch)\.ir$|\.co\.uk$|\.com\.tr$/i;

/** The «نام» the seller types in the registrar's DNS panel: the part before the registrable domain, «@» for the root. */
function recordName(host: string) {
  const labels = host.split(".").filter(Boolean);
  const keep = SECOND_LEVEL.test(host) ? 3 : 2;
  return labels.length > keep ? labels.slice(0, labels.length - keep).join(".") : "@";
}

function CopyValue({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }
  return (
    <div className="flex items-center gap-3 px-4 py-3">
      <span className="w-12 shrink-0 text-[13px] text-muted">{label}</span>
      <bdi dir="ltr" className="wrap-any min-w-0 flex-1 text-start font-mono text-[13px]">
        {value}
      </bdi>
      <button
        type="button"
        onClick={() => void copy()}
        aria-label={`کپی ${label}`}
        className="tap inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-xl px-3 text-[13px] text-warm hover:bg-canvas"
      >
        <Copy size={16} aria-hidden />
        {copied ? "کپی شد" : "کپی"}
      </button>
    </div>
  );
}

export default function DomainPage() {
  const [shop, setShop] = useState<ShopState | null>(null);
  const [loading, setLoading] = useState(true);
  const [domain, setDomain] = useState("");
  const [busy, setBusy] = useState<"" | "save" | "check" | "remove">("");
  const [error, setError] = useState("");

  function apply(data: ShopPayload) {
    setShop(data.shop);
    setDomain(personalDomainValue(data.shop));
  }

  useEffect(() => {
    api<ShopPayload>("/shop")
      .then(apply)
      .catch((err) => setError(err instanceof Error ? err.message : "خواندن فروشگاه نشد."))
      .finally(() => setLoading(false));
  }, []);

  async function run(kind: "save" | "check" | "remove", call: () => Promise<ShopPayload>) {
    setError("");
    setBusy(kind);
    try {
      apply(await call());
    } catch (err) {
      setError(err instanceof Error ? err.message : "انجام نشد. دوباره امتحان کن.");
    } finally {
      setBusy("");
    }
  }

  function save(event: FormEvent) {
    event.preventDefault();
    void run("save", () => api<ShopPayload>("/shop/domain", { method: "PATCH", body: JSON.stringify({ domain: domain.trim() }) }));
  }

  const saved = personalDomainValue(shop);
  const live = shopPublicUrl(shop);
  const built = Boolean(shop?.slug && shop?.publicHost);
  const target = String(shop?.cnameTarget || "").replace(/\.$/, "");
  const setupFailed = shop?.cnameSetup?.ok === false;
  const connected = Boolean(saved && shop?.cnameOk && !setupFailed);
  const name = saved ? recordName(saved) : "";

  return (
    <AppShell
      header={
        <div>
          <p className="text-sm text-muted">
            <Link href="/more" className="tap text-warm">
              بیشتر
            </Link>
          </p>
          <h1 className="text-lg font-bold">دامنهٔ اختصاصی</h1>
        </div>
      }
    >
      <div className="h-full space-y-4 overflow-y-auto p-4 [&>*]:mx-auto [&>*]:max-w-3xl">
        {loading ? (
          <div className="space-y-3" aria-busy="true">
            {[0, 1].map((item) => (
              <div key={item} className="h-28 animate-pulse rounded-2xl bg-canvas" />
            ))}
          </div>
        ) : !built ? (
          <EmptyState
            icon={Globe}
            title="اول فروشگاه را بساز"
            detail="دامنهٔ اختصاصی بعد از ساخت فروشگاه وصل می‌شود. تا آن موقع فروشگاه نشانی سوزان می‌گیرد."
            action={
              <Link href="/chat" className="inline-flex min-h-11 items-center rounded-xl bg-accentStrong px-4 text-sm text-onAccent">
                رفتن به چت
              </Link>
            }
          />
        ) : (
          <>
            <Card className="space-y-2">
              <p className="text-[13px] text-muted">نشانی فعلی فروشگاه</p>
              <div className="flex items-center justify-between gap-3">
                <bdi dir="ltr" className="wrap-any min-w-0 font-bold">
                  {live ? shopHostLabel(live) : shop?.publicHost}
                </bdi>
                {live ? (
                  <a
                    href={live}
                    target="_blank"
                    rel="noreferrer"
                    className="tap inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-xl px-3 text-sm text-warm hover:bg-canvas"
                  >
                    باز کردن
                    <ExternalLink size={16} aria-hidden />
                  </a>
                ) : null}
              </div>
              <p className="text-[13px] leading-6 text-muted">این نشانی همیشه کار می‌کند، حتی بعد از وصل شدن دامنهٔ خودت.</p>
            </Card>

            <Card>
              <form onSubmit={save} className="space-y-3">
                <label htmlFor="custom-domain" className="block font-bold">
                  دامنهٔ خودت
                </label>
                <Input
                  id="custom-domain"
                  dir="ltr"
                  placeholder="shop.example.com"
                  inputMode="url"
                  autoCapitalize="none"
                  autoCorrect="off"
                  spellCheck={false}
                  enterKeyHint="done"
                  value={domain}
                  onChange={(event) => setDomain(event.target.value)}
                />
                <p className="text-[13px] leading-6 text-muted">
                  زیردامنه مثل <bdi dir="ltr">shop.example.com</bdi> یا <bdi dir="ltr">www.example.com</bdi> بهتر است؛ بیشتر ثبت‌کننده‌ها روی خودِ{" "}
                  <bdi dir="ltr">example.com</bdi> رکورد CNAME نمی‌پذیرند.
                </p>
                {error ? (
                  <p className="text-sm leading-6 text-danger" role="alert">
                    {error}
                  </p>
                ) : null}
                <div className="flex flex-wrap gap-2">
                  <Button type="submit" disabled={Boolean(busy) || !domain.trim() || domain.trim() === saved}>
                    {busy === "save" ? "در حال ذخیره…" : "ذخیرهٔ دامنه"}
                  </Button>
                  {saved ? (
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={Boolean(busy)}
                      onClick={() =>
                        void run("remove", () => api<ShopPayload>("/shop/domain", { method: "PATCH", body: JSON.stringify({ domain: "" }) }))
                      }
                    >
                      {busy === "remove" ? "در حال برداشتن…" : "برداشتن دامنه"}
                    </Button>
                  ) : null}
                </div>
              </form>
            </Card>

            {saved ? (
              <>
                <section aria-labelledby="dns-title" className="space-y-2">
                  <h2 id="dns-title" className="px-1 font-bold">
                    این رکورد را در DNS دامنه‌ات بساز
                  </h2>
                  <p className="px-1 text-[13px] leading-6 text-muted">
                    در پنل همان‌جایی که دامنه را خریده‌ای، بخش DNS، یک رکورد تازه بساز. سوزان به حساب دامنه‌ات دسترسی ندارد.
                  </p>
                  <div className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface">
                    <CopyValue label="نوع" value="CNAME" />
                    <CopyValue label="نام" value={name} />
                    <CopyValue label="مقدار" value={target} />
                  </div>
                  {name !== "@" ? (
                    <p className="px-1 text-[13px] leading-6 text-muted">
                      بعضی پنل‌ها نام کامل را می‌خواهند: <bdi dir="ltr">{saved}</bdi>
                    </p>
                  ) : null}
                  {name === "@" ? (
                    <p className="flex gap-2 px-1 text-[13px] leading-6 text-warm">
                      <TriangleAlert size={16} className="mt-1 shrink-0" aria-hidden />
                      این خودِ دامنه است، نه زیردامنه. اگر ثبت‌کننده CNAME روی آن نپذیرفت، www یا shop را ذخیره کن.
                    </p>
                  ) : null}
                  <p className="px-1 text-[13px] leading-6 text-muted">
                    اگر DNS دامنه‌ات در کلودفلر است، پروکسی (ابر نارنجی) را برای این رکورد خاموش کن.
                  </p>
                </section>

                <Card className="space-y-3" aria-live="polite">
                  {connected ? (
                    <div className="flex items-start gap-3">
                      <CheckCircle2 size={22} className="mt-0.5 shrink-0 text-signal" aria-hidden />
                      <div className="min-w-0 space-y-1">
                        <p className="font-bold">وصل است</p>
                        <a href={`https://${saved}`} target="_blank" rel="noreferrer" className="wrap-any text-sm text-warm">
                          <bdi dir="ltr">{saved}</bdi>
                        </a>
                      </div>
                    </div>
                  ) : shop?.cnameOk && setupFailed ? (
                    <div className="flex items-start gap-3">
                      <TriangleAlert size={22} className="mt-0.5 shrink-0 text-danger" aria-hidden />
                      <div className="min-w-0 space-y-1">
                        <p className="font-bold">رکورد درست است؛ گواهی امن (HTTPS) هنوز آماده نشده</p>
                        <p className="text-sm leading-6 text-muted">{shop?.cnameSetup?.error || "دوباره بررسی کن؛ اگر ماند به پشتیبانی بگو."}</p>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-start gap-3">
                      <Clock size={22} className="mt-0.5 shrink-0 text-warm" aria-hidden />
                      <div className="min-w-0 space-y-1">
                        <p className="font-bold">در انتظار رکورد DNS</p>
                        <p className="text-sm leading-6 text-muted">
                          رسیدن تغییر DNS از چند دقیقه تا چند ساعت طول می‌کشد. تا آن موقع فروشگاه روی نشانی سوزان باز است.
                        </p>
                      </div>
                    </div>
                  )}
                  <Button
                    type="button"
                    variant="ghost"
                    className="gap-2"
                    disabled={Boolean(busy)}
                    onClick={() => void run("check", () => api<ShopPayload>("/shop/domain/check", { method: "POST" }))}
                  >
                    <RefreshCw size={16} className={busy === "check" ? "animate-spin" : ""} aria-hidden />
                    {busy === "check" ? "در حال بررسی…" : "بررسی دوباره"}
                  </Button>
                </Card>
              </>
            ) : null}
          </>
        )}
      </div>
    </AppShell>
  );
}
