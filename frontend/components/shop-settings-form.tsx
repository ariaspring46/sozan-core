"use client";

import { useEffect, useRef, useState } from "react";
import { Field } from "@/components/field";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { api } from "@/lib/api";
import { money } from "@/lib/digits";

type CatalogItem = { id: string; label: string; docs?: string; help?: string };
type StudioSettings = {
  mockSms: boolean;
  adminPhone: string;
  otpTtlSeconds: number;
  gatewayPublicUrl: string;
  storeName: string;
  storeTagline: string;
  paymentSandbox: boolean;
  paymentGateway: string;
  paymentMerchantId: string;
  paymentCurrency: string;
  paymentCallbackUrl: string;
  paymentApiKeySet?: boolean;
  smsProvider: string;
  smsTemplateId: string;
  smsTokenName: string;
  smsApiKeySet?: boolean;
  smsApiKey?: string;
  smsFromHub?: boolean;
  paymentApiKey?: string;
  paymentMerchantFromHub?: boolean;
  payment?: { gateway: string; sandbox: boolean; currency: string; ready: boolean; hint: string };
  smsProviders?: CatalogItem[];
  paymentGateways?: CatalogItem[];
  plan: string;
  billing?: { ready: boolean; gateway: string };
  hubAdmin?: boolean;
  walletAvailable?: number;
  voice?: { summary: string; tone: string; sampleReply: string };
  subscription?: {
    plan: string;
    label: string;
    sitesUsed: number;
    sitesLimit: number;
    features: string[];
    plans: {
      id: string;
      label: string;
      sites: number;
      priceToman?: number;
      listPrice?: number;
      discountPercent?: number;
      purchasable?: boolean;
      smsQuota?: number;
      features: string[];
    }[];
    discountUntilLabel?: string;
  };
};

export function ShopSettingsForm() {
  const [form, setForm] = useState<StudioSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pickedPlan, setPickedPlan] = useState("");
  const [confirmPay, setConfirmPay] = useState(false);
  const [couponCode, setCouponCode] = useState("");
  const [couponAmount, setCouponAmount] = useState<number | null>(null);
  const [plansOpen, setPlansOpen] = useState(false);
  const subRef = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    const jumpToPlans = window.location.hash === "#plans";
    const pay = new URLSearchParams(window.location.search).get("pay");
    if (pay) {
      window.history.replaceState({}, "", window.location.pathname);
      if (pay === "ok") setNotice("پرداخت موفق بود و اشتراک فعال شد.");
      else if (pay === "cancel") setNotice("پرداخت لغو شد.");
      else if (pay === "fail" || pay === "missing") setError("پرداخت کامل نشد. دوباره از همین صفحه اقدام کن.");
    }
    void api<StudioSettings>("/settings")
      .then((data) => {
        setForm({ ...data, smsApiKey: "", paymentApiKey: "" });
        if (jumpToPlans) {
          setPlansOpen(true);
          if (subRef.current) subRef.current.open = true;
          const jump = () => {
            const el = subRef.current;
            if (!el) return;
            // بدنهٔ برنامه overflow-hidden است و scrollIntoView را بی‌اثر می‌کند؛ خودمان می‌پریم.
            const scroller = el.closest(".overflow-y-auto");
            if (scroller instanceof HTMLElement) {
              scroller.scrollTop += el.getBoundingClientRect().top - scroller.getBoundingClientRect().top - 8;
            } else {
              el.scrollIntoView({ block: "start" });
            }
          };
          // کارت‌های بالای صفحه دیر بالا می‌آیند؛ دوباره تلاش کن تا جا افتاید.
          window.setTimeout(jump, 80);
          window.setTimeout(jump, 900);
        }
      })
      .catch((err) => setError(err.message));
  }, []);

  async function save() {
    if (!form) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const saved = await api<StudioSettings>("/settings", {
        method: "PATCH",
        body: JSON.stringify({
          ...(form.hubAdmin
            ? {
                mockSms: form.mockSms,
                adminPhone: form.adminPhone,
                otpTtlSeconds: form.otpTtlSeconds,
                gatewayPublicUrl: form.gatewayPublicUrl,
              }
            : {}),
          storeName: form.storeName,
          storeTagline: form.storeTagline,
          paymentSandbox: form.paymentSandbox,
          paymentGateway: form.paymentGateway,
          paymentMerchantId: form.paymentMerchantId,
          paymentCurrency: form.paymentCurrency,
          paymentCallbackUrl: form.paymentCallbackUrl,
          paymentApiKey: form.paymentApiKey || undefined,
          smsProvider: form.smsProvider,
          smsTemplateId: form.smsTemplateId,
          smsTokenName: form.smsTokenName,
          smsApiKey: form.smsApiKey || undefined,
        }),
      });
      setForm({ ...saved, smsApiKey: "", paymentApiKey: "" });
      setNotice("تنظیمات ذخیره شد و از همین لحظه برای ورود و فروشگاه اعمال می‌شود.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  const smsMeta = (form?.smsProviders || []).find((item) => item.id === form?.smsProvider);
  const payMeta = (form?.paymentGateways || []).find((item) => item.id === form?.paymentGateway);
  const pickedSpec = (form?.subscription?.plans || []).find((item) => item.id === pickedPlan);
  const pickedPrice = Number(pickedSpec?.priceToman || 0);
  const walletCovers = Boolean(form && pickedPrice > 0 && Number(form.walletAvailable || 0) >= pickedPrice);

  return (
      <div className="space-y-4">
          {form ? (
            <Card className="space-y-3">
              <h2 className="font-bold">فروشگاه و پرداخت</h2>
              <Field label="نام فروشگاه">
                <Input value={form.storeName} onChange={(event) => setForm({ ...form, storeName: event.target.value })} />
              </Field>
              <Field label="شعار">
                <Input value={form.storeTagline} onChange={(event) => setForm({ ...form, storeTagline: event.target.value })} />
              </Field>
              <Field label="درگاه پرداخت">
                <Select value={form.paymentGateway} onChange={(event) => setForm({ ...form, paymentGateway: event.target.value })}>
                  {(form.paymentGateways || []).map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </Select>
              </Field>
              {payMeta?.help ? (
                <p className="text-xs leading-6 text-muted">
                  {payMeta.help}
                  {payMeta.docs ? (
                    <>
                      {" "}
                      <a className="text-warm" href={payMeta.docs} target="_blank" rel="noreferrer">
                        اسناد
                      </a>
                    </>
                  ) : null}
                </p>
              ) : null}
              <p className="text-xs leading-6 text-muted">
                مرچنت شخصی زرین‌پال یا آیدی‌پی کمیسیون ندارد. اگر نباشد، لینک پرداخت و فروشگاه روی درگاه سوزان می‌رود و ۲٪ کم می‌شود. پول قابل‌برداشت در{" "}
                <a className="text-warm" href="/more/wallet">
                  کیف پول
                </a>{" "}
                است.
              </p>
              <p
                className={
                  form.paymentGateway === "mock"
                    ? "text-sm text-muted"
                    : (form.paymentGateway === "zarinpal" && (form.paymentMerchantId || form.paymentMerchantFromHub)) ||
                        (form.paymentGateway === "idpay" && (form.paymentApiKeySet || form.paymentApiKey))
                      ? "text-sm text-signal"
                      : "text-sm text-warm"
                }
              >
                {form.paymentGateway === "zarinpal"
                  ? form.paymentMerchantId || form.paymentMerchantFromHub
                    ? form.paymentMerchantFromHub
                      ? "مرچنت زرین‌پال هاب سوزان برای اشتراک آماده است."
                      : "مرچنت‌آیدی زرین‌پال آماده ذخیره است."
                    : "مرچنت‌آیدی ۳۶ کاراکتری زرین‌پال را بگذار."
                  : form.paymentGateway === "idpay"
                    ? form.paymentApiKeySet || form.paymentApiKey
                      ? "کلید آیدی‌پی آماده است."
                      : "کلید آیدی‌پی را بگذار."
                    : "فروش آنلاین خاموش است؛ فروش دستی ثبت می‌شود."}
              </p>
              {form.paymentGateway === "zarinpal" && !form.paymentMerchantFromHub ? (
                <Field label="مرچنت‌آیدی زرین‌پال">
                  <Input
                    dir="ltr"
                    placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                    value={form.paymentMerchantId}
                    onChange={(event) => setForm({ ...form, paymentMerchantId: event.target.value })}
                  />
                </Field>
              ) : null}
              {form.paymentGateway === "idpay" ? (
                <Field label="کلید آیدی‌پی">
                  <Input
                    dir="ltr"
                    type="password"
                    autoComplete="off"
                    placeholder={form.paymentApiKeySet ? "کلید ذخیره شده؛ برای عوض کردن کلید جدید بزن" : "کلید آیدی‌پی"}
                    value={form.paymentApiKey || ""}
                    onChange={(event) => setForm({ ...form, paymentApiKey: event.target.value })}
                  />
                </Field>
              ) : null}
              {form.paymentGateway !== "mock" ? (
                <>
                  <Field label="واحد پول">
                    <Select value={form.paymentCurrency} onChange={(event) => setForm({ ...form, paymentCurrency: event.target.value })}>
                      <option value="IRT">تومان (IRT)</option>
                      <option value="IRR">ریال (IRR)</option>
                    </Select>
                  </Field>
                  <Field label="آدرس بازگشت بعد از پرداخت">
                    <Input
                      dir="ltr"
                      placeholder="https://shop.example.com/pay/back"
                      value={form.paymentCallbackUrl}
                      onChange={(event) => setForm({ ...form, paymentCallbackUrl: event.target.value })}
                    />
                  </Field>
                  <label className="flex min-h-11 items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-accent"
                      checked={form.paymentSandbox}
                      onChange={(event) => setForm({ ...form, paymentSandbox: event.target.checked })}
                    />
                    درگاه آزمایشی
                  </label>
                </>
              ) : null}
            </Card>
          ) : (
            <p className="text-sm text-muted">در حال خواندن تنظیمات…</p>
          )}
          {form ? (
            <Card className="space-y-3">
              <h2 className="font-bold">درگاه پیامک</h2>
              {form.smsFromHub ? (
                <p className="text-sm text-signal">ورود پنل با پیامک سوزان فرستاده می‌شود.</p>
              ) : null}
              <label className="flex min-h-11 items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-accent"
                  checked={form.mockSms}
                  onChange={(event) => setForm({ ...form, mockSms: event.target.checked })}
                />
                پیامک آزمایشی (کد روی صفحه ورود)
              </label>
              {form.mockSms ? (
                <p className="text-sm text-muted">ورود بدون پیامک واقعی است. برای پیامک واقعی تیک را بردار.</p>
              ) : (
                <>
                  <Field label="درگاه">
                    <Select value={form.smsProvider} onChange={(event) => setForm({ ...form, smsProvider: event.target.value })}>
                      {(form.smsProviders || []).map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.label}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  {smsMeta?.help ? (
                    <p className="text-xs leading-6 text-muted">
                      {smsMeta.help}
                      {smsMeta.docs ? (
                        <>
                          {" "}
                          <a className="text-warm" href={smsMeta.docs} target="_blank" rel="noreferrer">
                            اسناد
                          </a>
                        </>
                      ) : null}
                    </p>
                  ) : null}
                  <Field label="کلید پیامک">
                    <Input
                      dir="ltr"
                      type="password"
                      autoComplete="off"
                      placeholder={
                        form.smsFromHub
                          ? "کلید هاب فعال است؛ برای عوض کردن کلید فروشگاه را بزن"
                          : form.smsApiKeySet
                            ? "کلید ذخیره شده؛ برای عوض کردن کلید جدید بزن"
                            : "کلید را اینجا بگذار"
                      }
                      value={form.smsApiKey || ""}
                      onChange={(event) => setForm({ ...form, smsApiKey: event.target.value })}
                    />
                  </Field>
                  <Field label={form.smsProvider === "smsir" ? "شناسهٔ قالب پیامک" : "نام الگوی پیامک"}>
                    <Input
                      dir="ltr"
                      placeholder={form.smsProvider === "smsir" ? "۱۲۳۴۵۶" : "نام الگو"}
                      value={form.smsTemplateId}
                      onChange={(event) => setForm({ ...form, smsTemplateId: event.target.value })}
                    />
                  </Field>
                  {form.smsProvider === "smsir" ? (
                    <Field label="نام پارامتر قالب">
                      <Input
                        dir="ltr"
                        placeholder="CODE"
                        value={form.smsTokenName}
                        onChange={(event) => setForm({ ...form, smsTokenName: event.target.value })}
                      />
                    </Field>
                  ) : null}
                </>
              )}
              {form.hubAdmin ? <details className="rounded-xl border border-line bg-paper px-3 py-2">
                <summary className="cursor-pointer text-sm text-muted">تنظیمات پیشرفته استودیو</summary>
                <div className="mt-3 space-y-3">
                  <Field label="شماره مدیر استودیو">
                    <Input dir="ltr" value={form.adminPhone} onChange={(event) => setForm({ ...form, adminPhone: event.target.value })} />
                  </Field>
                  <Field label="آدرس عمومی Gateway">
                    <Input dir="ltr" value={form.gatewayPublicUrl} onChange={(event) => setForm({ ...form, gatewayPublicUrl: event.target.value })} />
                  </Field>
                </div>
              </details> : null}
            </Card>
          ) : null}
          {form?.subscription ? (
            <details ref={subRef} id="plans" className="rounded-2xl border border-line bg-surface p-4 shadow-card">
              <summary className="cursor-pointer font-bold">
                اشتراک {form.subscription.label}
              </summary>
              <div className="mt-3 space-y-3">
              <p className="text-sm text-muted">
                وب‌سایت {form.subscription.sitesUsed} از {form.subscription.sitesLimit || "∞"}
              </p>
              {form.voice?.summary ? (
                <p className="text-sm leading-7">لحن یادگرفته: {form.voice.tone}. {form.voice.summary}</p>
              ) : (
                <p className="text-sm text-muted">هنوز لحن فروشنده از کانال یاد گرفته نشده.</p>
              )}
              <Button variant="ghost" type="button" onClick={() => setPlansOpen((open) => !open)}>
                {plansOpen ? "بستن پلن‌ها" : "تغییر اشتراک"}
              </Button>
              {plansOpen ? (
                <div className="space-y-2">
                  {form.subscription.plans.map((plan) => {
                    const selected = (pickedPlan || form.plan) === plan.id;
                    const active = form.plan === plan.id;
                    return (
                      <button
                        key={plan.id}
                        type="button"
                        className={`w-full rounded-xl border p-3 text-right ${
                          selected ? "border-accent bg-paper" : "border-line bg-surface"
                        }`}
                        disabled={busy}
                        onClick={() => {
                          setPickedPlan(plan.id);
                          setConfirmPay(false);
                          setError("");
                          setNotice("");
                        }}
                      >
                        <p className="font-medium">
                          {plan.label}
                          {active ? <span className="mr-2 text-xs text-warm">فعال</span> : null}
                        </p>
                        <p className="text-xs text-muted">
                          {plan.sites === 1 ? "یک وب‌سایت" : plan.sites === 0 ? "وب‌سایت نامحدود" : `تا ${plan.sites} وب‌سایت`}
                          {plan.listPrice && plan.priceToman && plan.listPrice > plan.priceToman ? (
                            <span className="mx-1 line-through">{money(plan.listPrice)}</span>
                          ) : null}
                          {plan.priceToman ? ` · ${money(plan.priceToman)} تومان در ماه` : " · رایگان"}
                          {plan.discountPercent ? ` · ٪${money(plan.discountPercent)} تخفیف` : ""}
                          {plan.purchasable === false ? " · به‌زودی" : ""}
                          {plan.smsQuota ? ` · ${money(plan.smsQuota)} پیامک` : ""}
                        </p>
                      </button>
                    );
                  })}
                  {form.subscription.discountUntilLabel ? (
                    <p className="text-xs text-muted">تخفیف تا {form.subscription.discountUntilLabel}</p>
                  ) : null}
                  {pickedPlan && pickedPlan !== form.plan && pickedSpec?.purchasable === false ? (
                    <Button disabled>به‌زودی</Button>
                  ) : null}
                  {pickedPlan && pickedPlan !== form.plan && pickedSpec?.purchasable !== false ? (
                    <div className="space-y-2">
                      {confirmPay && pickedPlan !== "free" && form.billing?.ready ? (
                        <div className="space-y-2">
                          <Input
                            value={couponCode}
                            placeholder="کد تخفیف"
                            onChange={(event) => {
                              setCouponCode(event.target.value);
                              setCouponAmount(null);
                            }}
                          />
                          <Button
                            variant="ghost"
                            type="button"
                            disabled={busy || !couponCode.trim()}
                            onClick={() => {
                              setBusy(true);
                              setError("");
                              void api<{ amount: number }>("/billing/coupon-preview", {
                                method: "POST",
                                body: JSON.stringify({ plan: pickedPlan, code: couponCode.trim() }),
                              })
                                .then((data) => setCouponAmount(data.amount))
                                .catch((err) => setError(err instanceof Error ? err.message : "این کد تخفیف معتبر نیست"))
                                .finally(() => setBusy(false));
                            }}
                          >
                            اعمال کد
                          </Button>
                          {couponAmount != null ? <p className="text-sm">با کد: {money(couponAmount)} تومان</p> : null}
                        </div>
                      ) : null}
                      {confirmPay && pickedPlan !== "free" ? (
                        <p className="text-sm text-muted">
                          {walletCovers
                            ? `موجودی کیف ${money(form.walletAvailable || 0)} تومان است و اشتراک ${pickedSpec?.label} از کیف کم می‌شود.`
                            : form.billing?.ready
                              ? `بعد از تأیید به زرین‌پال می‌روی و اشتراک ${pickedSpec?.label} فعال می‌شود.`
                              : "پرداخت به‌زودی فعال می‌شود"}
                        </p>
                      ) : null}
                      <div className="flex flex-wrap gap-2">
                        <Button
                          disabled={busy || (pickedPlan !== "free" && !walletCovers && !form.billing?.ready)}
                          onClick={() => {
                            const paid = pickedPlan !== "free";
                            if (paid && !confirmPay) {
                              setConfirmPay(true);
                              return;
                            }
                            setBusy(true);
                            setError("");
                            if (!paid) {
                              void api<StudioSettings>("/settings", {
                                method: "PATCH",
                                body: JSON.stringify({ plan: pickedPlan }),
                              })
                                .then((saved) => {
                                  setForm({ ...saved, smsApiKey: "", paymentApiKey: "" });
                                  setNotice(`اشتراک ${saved.subscription?.label || saved.plan} فعال شد.`);
                                  setPickedPlan("");
                                  setConfirmPay(false);
                                  setPlansOpen(false);
                                })
                                .catch((err) => setError(err instanceof Error ? err.message : "خطا"))
                                .finally(() => setBusy(false));
                              return;
                            }
                            void api<{ activated?: boolean; startPayUrl?: string; subscription?: StudioSettings["subscription"] }>(
                              "/billing/subscribe",
                              {
                                method: "POST",
                                body: JSON.stringify({
                                  plan: pickedPlan,
                                  code: form.billing?.ready ? couponCode.trim() : "",
                                }),
                              },
                            )
                              .then((data) => {
                                if (data.startPayUrl) {
                                  window.location.href = data.startPayUrl;
                                  return;
                                }
                                setNotice("اشتراک فعال شد.");
                                setPickedPlan("");
                                setConfirmPay(false);
                                setPlansOpen(false);
                                return api<StudioSettings>("/settings").then((saved) =>
                                  setForm({ ...saved, smsApiKey: "", paymentApiKey: "" }),
                                );
                              })
                              .catch((err) => setError(err instanceof Error ? err.message : "خطا"))
                              .finally(() => setBusy(false));
                          }}
                        >
                          {pickedPlan === "free"
                            ? "فعال‌سازی رایگان"
                            : !walletCovers && !form.billing?.ready
                              ? "پرداخت به‌زودی فعال می‌شود"
                              : confirmPay
                                ? walletCovers
                                  ? "پرداخت از کیف"
                                  : "پرداخت با زرین‌پال"
                                : "پرداخت و فعال‌سازی"}
                        </Button>
                        <Button
                          variant="ghost"
                          type="button"
                          disabled={busy}
                          onClick={() => {
                            setPickedPlan("");
                            setConfirmPay(false);
                          }}
                        >
                          انصراف
                        </Button>
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}
              </div>
            </details>
          ) : null}
        {form ? (
          <div className="shrink-0 bg-paper/80 px-4 py-3 backdrop-blur-md">
            {error ? <p className="mb-2 text-sm text-danger">{error}</p> : null}
            {notice ? <p className="mb-2 text-sm text-signal">{notice}</p> : null}
            <Button className="w-full" disabled={busy} onClick={() => void save()}>
              ذخیره تنظیمات
            </Button>
          </div>
        ) : null}
      </div>
  );
}
