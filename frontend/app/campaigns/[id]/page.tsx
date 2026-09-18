"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api, Campaign, getApiBase } from "@/lib/api";
import { AppShell } from "@/components/app-shell";
import { StudioNav } from "@/components/studio-nav";
import { AuthMedia } from "@/components/auth-media";
import { Field } from "@/components/field";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

export default function CampaignDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const ig = useMemo(
    () => campaign?.copies.find((c) => c.channel === "instagram")?.body || "",
    [campaign]
  );
  const tg = useMemo(
    () => campaign?.copies.find((c) => c.channel === "telegram")?.body || "",
    [campaign]
  );
  const wa = useMemo(
    () => campaign?.copies.find((c) => c.channel === "whatsapp")?.body || "",
    [campaign]
  );
  const [title, setTitle] = useState("");
  const [subtitle, setSubtitle] = useState("");
  const [cta, setCta] = useState("");
  const [instagram, setInstagram] = useState("");
  const [telegram, setTelegram] = useState("");
  const [whatsapp, setWhatsapp] = useState("");

  async function load() {
    const data = await api<Campaign>(`/campaigns/${id}`);
    setCampaign(data);
    setTitle(data.title);
    setSubtitle(data.subtitle);
    setCta(data.cta);
    setInstagram(data.copies.find((c) => c.channel === "instagram")?.body || "");
    setTelegram(data.copies.find((c) => c.channel === "telegram")?.body || "");
    setWhatsapp(data.copies.find((c) => c.channel === "whatsapp")?.body || "");
  }

  useEffect(() => {
    void load().catch((err) => setError(err.message));
  }, [id]);

  async function save() {
    setBusy(true);
    setError("");
    try {
      const data = await api<Campaign>(`/campaigns/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          title,
          subtitle,
          cta,
          instagram_caption: instagram,
          telegram_caption: telegram,
          whatsapp_caption: whatsapp,
        }),
      });
      setCampaign(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  async function compose() {
    setBusy(true);
    setError("");
    try {
      await save();
      const data = await api<Campaign>(`/campaigns/${id}/compose`, { method: "POST" });
      setCampaign(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  async function download() {
    setBusy(true);
    setError("");
    try {
      const token = localStorage.getItem("sozan_token");
      const res = await fetch(
        `${getApiBase()}/campaigns/${id}/export`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} }
      );
      if (!res.ok) throw new Error("دانلود نشد");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${campaign?.slug || "campaign"}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  if (!campaign) {
    return (
      <AppShell header={<h1 className="text-lg font-bold">کمپین</h1>}>
        <p className="p-8 text-muted">{error || "در حال بارگذاری…"}</p>
      </AppShell>
    );
  }

  const overlays = campaign.assets.filter((a) => a.kind === "overlay" || a.kind === "video");

  return (
    <AppShell
      header={
        <div>
          <p className="text-sm text-muted">استودیو</p>
          <h1 className="text-lg font-bold">{campaign.title}</h1>
        </div>
      }
    >
    <main className="h-full space-y-4 overflow-y-auto p-4">
      <StudioNav current="campaigns" />
      <Link className="text-sm text-warm" href="/campaigns">
        بازگشت به کمپین‌ها
      </Link>
      <div className="grid gap-4">
        <Card className="space-y-3">
          <Field label="تیتر">
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <Field label="زیرتیتر">
            <Input value={subtitle} onChange={(e) => setSubtitle(e.target.value)} />
          </Field>
          <Field label="دعوت به اقدام">
            <Input value={cta} onChange={(e) => setCta(e.target.value)} />
          </Field>
        </Card>
        <Card className="space-y-3">
          <Field label="کپشن اینستاگرام">
            <Textarea value={instagram} onChange={(e) => setInstagram(e.target.value)} />
          </Field>
          <Field label="کپشن تلگرام">
            <Textarea value={telegram} onChange={(e) => setTelegram(e.target.value)} />
          </Field>
          <Field label="پیام واتساپ">
            <Textarea value={whatsapp} onChange={(e) => setWhatsapp(e.target.value)} />
          </Field>
        </Card>
      </div>
      <div className="flex flex-wrap gap-3">
        <Button disabled={busy} onClick={() => void save()}>
          ذخیره متن
        </Button>
        <Button disabled={busy} onClick={() => void compose()}>
          بساز ویدیو
        </Button>
        <Button className="bg-surface" disabled={busy} onClick={() => void download()}>
          دانلود پک
        </Button>
      </div>
      {error ? <p className="text-sm text-danger">{error}</p> : null}
      <section className="grid gap-4 md:grid-cols-2">
        {overlays.map((asset) => (
          <Card key={asset.id}>
            <p className="mb-2 text-sm text-muted">
              {asset.channel} — {asset.format}
            </p>
            {asset.format === "captions" ? (
              <p className="whitespace-pre-wrap text-sm">{ig || tg || wa}</p>
            ) : (
              <AuthMedia
                campaignId={campaign.id}
                relPath={asset.rel_path}
                kind={asset.kind}
                alt={asset.format}
              />
            )}
          </Card>
        ))}
      </section>
    </main>
    </AppShell>
  );
}
