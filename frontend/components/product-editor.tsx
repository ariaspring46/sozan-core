"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AuthImage } from "@/components/auth-image";
import { Field } from "@/components/field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api, catalogImageUrl } from "@/lib/api";
import { money, parseNonNegativeInt } from "@/lib/digits";

export type Product = {
  id: string;
  title: string;
  price: number;
  stock: number;
  sku: string;
  image?: string;
  images?: string[];
  source?: string;
  sourceHandle?: string;
  description?: string;
  category?: string;
  subcategory?: string;
  colors?: string[];
  sizes?: string;
  discount?: number;
  finalPrice?: number;
  priceNote?: string;
  priceLabel?: string;
};

export type CategoryOption = {
  title: string;
  subcategories: string[];
  count: number;
};

export type ShopMeta = {
  live?: boolean;
  slug?: string;
  pendingBuild?: number;
  hidePrices?: boolean;
  runtimeCatalog?: boolean;
  needsBuild?: boolean;
};

export type SyncResult = {
  live?: boolean;
  hint?: string;
  error?: string;
  pendingMenu?: boolean;
};

export type CatalogResponse = {
  products: Product[];
  categories?: CategoryOption[];
  shop?: ShopMeta;
  sync?: SyncResult;
};

const PRICE_MODES = [
  { value: "", label: "قیمت عادی" },
  { value: "دایرکت", label: "دایرکت" },
  { value: "تماس بگیرید", label: "تماس بگیرید" },
] as const;

function productImages(product: Product | null): string[] {
  const names: string[] = [];
  for (const item of product?.images || []) {
    if (item && !names.includes(item)) names.push(item);
  }
  if (product?.image && !names.includes(product.image)) names.unshift(product.image);
  return names.slice(0, 5);
}

function snapshot(values: {
  title: string;
  description: string;
  price: string;
  discount: string;
  priceNote: string;
  stock: string;
  sku: string;
  category: string;
  subcategory: string;
  colors: string[];
  sizes: string;
  images: string[];
}) {
  return JSON.stringify(values);
}

export function ProductEditor({
  product,
  categories,
  onClose,
  onSaved,
  onDeleted,
}: {
  product: Product | null;
  categories: CategoryOption[];
  onClose: () => void;
  onSaved: (data: CatalogResponse) => void;
  onDeleted?: (data: CatalogResponse) => void;
}) {
  const [title, setTitle] = useState(product?.title || "");
  const [description, setDescription] = useState(product?.description || "");
  const [price, setPrice] = useState(product?.price ? String(product.price) : "");
  const [discount, setDiscount] = useState(product?.discount ? String(product.discount) : "");
  const [priceNote, setPriceNote] = useState(product?.priceNote || "");
  const [stock, setStock] = useState(product ? String(product.stock ?? 0) : "0");
  const [sku, setSku] = useState(product?.sku || "");
  const [category, setCategory] = useState(product?.category || "");
  const [subcategory, setSubcategory] = useState(product?.subcategory || "");
  const [colors, setColors] = useState<string[]>(product?.colors || []);
  const [colorDraft, setColorDraft] = useState("");
  const [sizes, setSizes] = useState(product?.sizes || "");
  const [images, setImages] = useState<string[]>(productImages(product));
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(false);
  const [error, setError] = useState("");
  const [mounted, setMounted] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const initial = useRef("");

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") requestClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  useEffect(() => {
    initial.current = snapshot({
      title: product?.title || "",
      description: product?.description || "",
      price: product?.price ? String(product.price) : "",
      discount: product?.discount ? String(product.discount) : "",
      priceNote: product?.priceNote || "",
      stock: product ? String(product.stock ?? 0) : "0",
      sku: product?.sku || "",
      category: product?.category || "",
      subcategory: product?.subcategory || "",
      colors: product?.colors || [],
      sizes: product?.sizes || "",
      images: productImages(product),
    });
  }, [product]);

  const current = snapshot({
    title,
    description,
    price,
    discount,
    priceNote,
    stock,
    sku,
    category,
    subcategory,
    colors,
    sizes,
    images,
  });
  const dirty = current !== initial.current;
  const priced = priceNote === "";
  const parsedPrice = parseNonNegativeInt(price || "0");
  const parsedDiscount = parseNonNegativeInt(discount || "0");
  const parsedStock = parseNonNegativeInt(stock || "0");
  const valid =
    Boolean(title.trim()) &&
    parsedPrice !== null &&
    parsedDiscount !== null &&
    parsedDiscount <= 90 &&
    parsedStock !== null;
  const finalPrice =
    priced && parsedPrice && parsedDiscount
      ? Math.floor((parsedPrice * (100 - parsedDiscount)) / 100)
      : parsedPrice || 0;
  const subOptions = useMemo(() => {
    const match = categories.find((item) => item.title === category.trim());
    return match?.subcategories || [];
  }, [categories, category]);

  function addColor(raw: string) {
    const next = raw
      .split(/[،,]/)
      .map((item) => item.trim())
      .filter(Boolean);
    if (!next.length) return;
    setColors((prev) => {
      const out = [...prev];
      for (const item of next) {
        if (!out.includes(item) && out.length < 6) out.push(item);
      }
      return out;
    });
    setColorDraft("");
  }

  function requestClose() {
    if (dirty && !window.confirm("تغییرات ذخیره نشده؛ ببندم؟")) return;
    onClose();
  }

  async function upload(file: File) {
    if (images.length >= 5) {
      setError("حداکثر پنج عکس.");
      return;
    }
    setUploading(true);
    setError("");
    try {
      const body = new FormData();
      body.append("file", file);
      const data = await api<{ image: string }>("/catalog/upload", { method: "POST", body });
      setImages((prev) => (prev.includes(data.image) ? prev : [...prev, data.image].slice(0, 5)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "آپلود نشد");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!valid) {
      setError("نام، قیمت و موجودی را درست بنویس.");
      return;
    }
    setBusy(true);
    setError("");
    const payload = {
      title: title.trim(),
      description: description.trim(),
      price: priced ? parsedPrice || 0 : parsedPrice || 0,
      discount: parsedDiscount || 0,
      priceNote,
      stock: parsedStock || 0,
      sku: sku.trim(),
      category: category.trim(),
      subcategory: subcategory.trim(),
      colors,
      sizes: sizes.trim(),
      image: images[0] || "",
      images,
    };
    try {
      const data = product
        ? await api<CatalogResponse>(`/catalog/${product.id}`, { method: "PATCH", body: JSON.stringify(payload) })
        : await api<CatalogResponse>("/catalog", { method: "POST", body: JSON.stringify(payload) });
      initial.current = current;
      onSaved(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ذخیره نشد");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!product) return;
    if (!pendingDelete) {
      setPendingDelete(true);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const data = await api<CatalogResponse>(`/catalog/${product.id}`, { method: "DELETE" });
      onDeleted?.(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "حذف نشد");
      setBusy(false);
    }
  }

  const sheet = (
    <div className="fixed inset-0 z-[80] flex items-end bg-black/55 backdrop-blur-[2px] sm:items-center sm:p-4" onClick={requestClose}>
      <div
        className="flex max-h-[92dvh] w-full flex-col rounded-t-3xl border border-line bg-paper shadow-card sm:mx-auto sm:max-w-lg sm:rounded-3xl"
        onClick={(event) => event.stopPropagation()}
        dir="rtl"
      >
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          <h2 className="text-lg font-bold">{product ? "ویرایش کالا" : "افزودن کالا"}</h2>
          <Button type="button" variant="ghost" onClick={requestClose}>
            بستن
          </Button>
        </div>
        <form className="flex min-h-0 flex-1 flex-col" onSubmit={(event) => void save(event)}>
          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
            {error ? <p className="text-sm text-danger">{error}</p> : null}
            <div>
              <p className="mb-2 text-sm">عکس‌ها</p>
              <div className="flex gap-2 overflow-x-auto pb-1">
                {images.map((name, index) => (
                  <div key={name} className="relative w-24 shrink-0">
                    <AuthImage src={catalogImageUrl(name)} alt="" className="h-24 w-24 rounded-xl object-cover" />
                    {index === 0 ? (
                      <span className="absolute inset-x-1 top-1 rounded-full bg-accent/90 px-2 py-0.5 text-center text-[10px] text-onAccent">
                        اصلی
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="absolute inset-x-1 top-1 rounded-full bg-paper/90 px-2 py-0.5 text-[10px]"
                        onClick={() => setImages([name, ...images.filter((item) => item !== name)])}
                      >
                        اصلی کن
                      </button>
                    )}
                    <button
                      type="button"
                      className="absolute inset-x-1 bottom-1 rounded-full bg-paper/90 px-2 py-0.5 text-[10px] text-danger"
                      onClick={() => setImages(images.filter((item) => item !== name))}
                    >
                      حذف
                    </button>
                  </div>
                ))}
                {images.length < 5 ? (
                  <button
                    type="button"
                    className="flex h-24 w-24 shrink-0 items-center justify-center rounded-xl border border-dashed border-line text-sm text-muted"
                    disabled={uploading}
                    onClick={() => fileRef.current?.click()}
                  >
                    {uploading ? "…" : "افزودن عکس"}
                  </button>
                ) : null}
              </div>
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void upload(file);
                }}
              />
            </div>
            <Field label="نام کالا">
              <Input value={title} onChange={(event) => setTitle(event.target.value)} />
            </Field>
            <Field label="توضیح">
              <Textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={3} className="min-h-24" />
            </Field>
            <Field label="حالت قیمت">
              <Select value={priceNote} onChange={(event) => setPriceNote(event.target.value)}>
                {PRICE_MODES.map((item) => (
                  <option key={item.value || "normal"} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="قیمت به تومان">
              <Input
                dir="ltr"
                inputMode="numeric"
                value={price}
                disabled={!priced}
                onChange={(event) => setPrice(event.target.value)}
              />
              {priced && parsedPrice ? <p className="text-xs text-muted">{money(parsedPrice)} تومان</p> : null}
            </Field>
            <Field label="تخفیف ٪">
              <Input
                dir="ltr"
                inputMode="numeric"
                value={discount}
                disabled={!priced}
                onChange={(event) => setDiscount(event.target.value)}
              />
              {priced && parsedDiscount && parsedPrice ? (
                <p className="text-xs text-muted">قیمت نهایی {money(finalPrice)} تومان</p>
              ) : null}
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="موجودی">
                <Input dir="ltr" inputMode="numeric" value={stock} onChange={(event) => setStock(event.target.value)} />
              </Field>
              <Field label="شناسه انبار">
                <Input dir="ltr" value={sku} onChange={(event) => setSku(event.target.value)} />
              </Field>
            </div>
            <Field label="دسته">
              <Input list="sales-categories" value={category} onChange={(event) => setCategory(event.target.value)} />
              <datalist id="sales-categories">
                {categories.map((item) => (
                  <option key={item.title} value={item.title} />
                ))}
              </datalist>
            </Field>
            <Field label="زیردسته">
              <Input list="sales-subcategories" value={subcategory} onChange={(event) => setSubcategory(event.target.value)} />
              <datalist id="sales-subcategories">
                {subOptions.map((item) => (
                  <option key={item} value={item} />
                ))}
              </datalist>
            </Field>
            <Field label="رنگ‌ها">
              <div className="flex flex-wrap gap-1">
                {colors.map((item) => (
                  <button
                    key={item}
                    type="button"
                    className="rounded-full border border-line px-2 py-1 text-xs"
                    onClick={() => setColors(colors.filter((color) => color !== item))}
                  >
                    {item} ×
                  </button>
                ))}
              </div>
              <Input
                value={colorDraft}
                placeholder="رنگ و Enter"
                onChange={(event) => setColorDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === ",") {
                    event.preventDefault();
                    addColor(colorDraft);
                  }
                }}
                onBlur={() => addColor(colorDraft)}
              />
            </Field>
            <Field label="سایز">
              <Input value={sizes} onChange={(event) => setSizes(event.target.value)} />
            </Field>
          </div>
          <div className="flex flex-wrap gap-2 border-t border-line p-4">
            <Button type="submit" disabled={busy || uploading || !dirty || !valid}>
              ذخیره
            </Button>
            <Button type="button" variant="ghost" disabled={busy} onClick={requestClose}>
              انصراف
            </Button>
            {product ? (
              <Button type="button" variant="ghost" disabled={busy} onClick={() => void remove()}>
                {pendingDelete ? "تأیید حذف" : "حذف کالا"}
              </Button>
            ) : null}
          </div>
        </form>
      </div>
    </div>
  );

  if (!mounted) return null;
  return createPortal(sheet, document.body);
}
