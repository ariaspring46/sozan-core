"use client";

import { ChangeEvent, useEffect, useState } from "react";
import { api, Brand, getApiBase, getToken } from "@/lib/api";
import { AuthImage } from "@/components/auth-image";
import { Field } from "@/components/field";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

function LogoMotionPreview({ bust }: { bust: number }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let objectUrl: string | null = null;
    const run = async () => {
      const token = getToken();
      const res = await fetch(`${getApiBase()}/brand/motion/logo-reel.mp4?t=${bust}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) return;
      objectUrl = URL.createObjectURL(await res.blob());
      setUrl(objectUrl);
    };
    void run();
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [bust]);
  if (!url) return <div className="aspect-[9/16] max-h-80 w-44 animate-pulse rounded-lg bg-paper" />;
  return (
    <video
      className="max-h-80 w-44 rounded-lg bg-paper"
      src={url}
      controls
      playsInline
      autoPlay
      muted
      loop
    />
  );
}

export function BrandIdentitySection() {
  const [name, setName] = useState("سوزان");
  const [description, setDescription] = useState("");
  const [hasCharacter, setHasCharacter] = useState(false);
  const [hasMotion, setHasMotion] = useState(false);
  const [motionNote, setMotionNote] = useState("");
  const [bust, setBust] = useState(Date.now());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    void api<Brand>("/brand")
      .then((data) => {
        setName(data.name);
        setDescription(data.description);
        setHasCharacter(data.has_character);
        setHasMotion(Boolean(data.has_motion));
      })
      .catch((err) => setError(err.message));
  }, []);

  async function save() {
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      const data = await api<Brand>("/brand", {
        method: "PATCH",
        body: JSON.stringify({ name, description }),
      });
      setName(data.name);
      setDescription(data.description);
      setHasCharacter(data.has_character);
      setHasMotion(Boolean(data.has_motion));
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  async function upload(kind: "logo" | "character", file: File) {
    setBusy(true);
    setError("");
    try {
      const body = new FormData();
      body.append("file", file);
      const data = await api<Brand>(`/brand/${kind}`, { method: "POST", body });
      setHasCharacter(data.has_character);
      setBust(Date.now());
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  async function makeMotion() {
    setBusy(true);
    setError("");
    try {
      const out = await api<{ note?: string }>("/brand/logo-motion", { method: "POST" });
      setHasMotion(true);
      setMotionNote(out.note || "");
      setBust(Date.now());
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  function onFile(kind: "logo" | "character") {
    return (e: ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) void upload(kind, file);
      e.target.value = "";
    };
  }

  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-start gap-x-6 gap-y-4">
        <div className="flex flex-col items-center gap-2">
          {hasCharacter ? (
            <AuthImage
              src={`${getApiBase()}/brand/character`}
              alt="کاراکتر سوزان"
              bust={bust}
              className="h-40 w-32 rounded-xl object-cover"
            />
          ) : (
            <div className="h-40 w-32 rounded-xl bg-paper" />
          )}
          <label className="inline-flex min-h-11 cursor-pointer items-center text-sm text-warm">
            بارگذاری کاراکتر
            <input type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={onFile("character")} />
          </label>
        </div>
        <div className="flex flex-col items-center gap-2">
          <AuthImage
            src={`${getApiBase()}/brand/logo`}
            alt="لوگوی سوزان"
            bust={bust}
            className="h-16 w-auto max-w-56 object-contain"
          />
          <label className="inline-flex min-h-11 cursor-pointer items-center text-sm text-warm">
            بارگذاری لوگو
            <input type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={onFile("logo")} />
          </label>
        </div>
        <div className="w-full min-w-0 space-y-3 sm:w-auto sm:min-w-[14rem] sm:flex-1">
          <h2 className="text-lg font-bold">هویت سوزان</h2>
          <Field label="نام">
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
        </div>
      </div>
      <Field label="توضیح کامل: کارها و کاراکتر">
        <Textarea
          className="min-h-64"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="اینجا هرچه می‌خواهی دربارهٔ سوزان بنویس…"
        />
      </Field>
      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={busy} onClick={() => void save()}>
          ذخیره هویت
        </Button>
        <Button variant="ghost" disabled={busy} onClick={() => void makeMotion()}>
          بساز لوگو موشن
        </Button>
        {saved ? <p className="text-sm text-signal">ذخیره شد</p> : null}
        {error ? <p className="text-sm text-danger">{error}</p> : null}
      </div>
      {hasMotion ? (
        <div className="space-y-2">
          <p className="text-sm text-muted">
            لوگو موشن — فانوس، شعله، قفل Sozan-Core
            {motionNote ? ` · ${motionNote}` : ""}
          </p>
          <div className="flex flex-wrap gap-4">
            <LogoMotionPreview bust={bust} />
          </div>
        </div>
      ) : null}
    </Card>
  );
}
