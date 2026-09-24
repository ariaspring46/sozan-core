"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AuthImage } from "@/components/auth-image";
import { ProductEditor, type CatalogResponse, type CategoryOption, type Product, type ShopMeta, type SyncResult } from "@/components/product-editor";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, catalogImageUrl } from "@/lib/api";
import { money, priceText } from "@/lib/digits";
import { EmptyState } from "@/components/empty-state";

function missingPhoto(product: Product) {
  const thumb = product.images?.[0] || product.image || "";
  return !thumb || thumb.includes("hero.png");
}

function missingPrice(product: Product) {
  return !(Number(product.price) > 0) || Boolean(product.priceNote);
}

function applyCatalog(
  data: CatalogResponse,
  setProducts: (rows: Product[]) => void,
  setCategories: (rows: CategoryOption[]) => void,
  setShop: (row: ShopMeta | null) => void,
  setHint: (text: string) => void,
) {
  setProducts(data.products || []);
  if (data.categories) setCategories(data.categories);
  if (data.shop) setShop(data.shop);
  const sync = data.sync as SyncResult | undefined;
  if (sync?.hint) setHint(sync.hint);
  else if (sync?.error) setHint(sync.error);
}

export function InventoryCatalog() {
  const [products, setProducts] = useState<Product[]>([]);
  const [categories, setCategories] = useState<CategoryOption[]>([]);
  const [shop, setShop] = useState<ShopMeta | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [hint, setHint] = useState("");
  const [editor, setEditor] = useState<Product | null | "new">(null);
  const searchParams = useSearchParams();
  const focus = searchParams.get("focus");
  const focusedRef = useRef(false);

  async function load() {
    const catalog = await api<CatalogResponse>("/catalog").catch(() => ({
      products: [] as Product[],
      categories: [] as CategoryOption[],
      shop: null,
    }));
    setProducts(catalog.products || []);
    setCategories(catalog.categories || []);
    setShop(catalog.shop || null);
  }

  useEffect(() => {
    void load()
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (loading || editor || focusedRef.current) return;
    if (focus !== "price") return;
    const missing = products.find((product) => !(Number(product.price) > 0) || product.priceNote);
    if (missing) {
      focusedRef.current = true;
      setEditor(missing);
    }
  }, [loading, products, focus, editor]);

  const visible = useMemo(() => {
    const needle = query.trim();
    const rows = products.filter((product) => {
      if (category && product.category !== category) return false;
      if (!needle) return true;
      const blob = `${product.title} ${product.category || ""} ${product.subcategory || ""} ${product.sku || ""}`;
      return blob.includes(needle);
    });
    return [...rows].sort((left, right) => {
      const leftGap = Number(missingPhoto(left) || missingPrice(left));
      const rightGap = Number(missingPhoto(right) || missingPrice(right));
      return rightGap - leftGap;
    });
  }, [products, query, category]);

  async function bump(id: string, delta: number) {
    setBusy(true);
    setError("");
    try {
      const data = await api<CatalogResponse>(`/catalog/${id}/stock`, {
        method: "POST",
        body: JSON.stringify({ delta }),
      });
      applyCatalog(data, setProducts, setCategories, setShop, setHint);
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="h-full space-y-4 overflow-y-auto p-4">
        {error ? <p className="text-sm text-danger">{error}</p> : null}
        {shop?.needsBuild ? (
          <p className="rounded-xl border border-line px-3 py-2 text-sm leading-7">
            برای نمایش کالاها روی سایت، بیلد بزن{" "}
            <Link href="/shop" className="text-warm">
              رفتن به فروشگاه
            </Link>
          </p>
        ) : shop?.live ? (
          <p className="rounded-xl bg-canvas px-3 py-2 text-sm leading-7 text-muted">تغییرات همان لحظه روی سایت می‌رود.</p>
        ) : (
          <p className="rounded-xl bg-canvas px-3 py-2 text-sm leading-7 text-muted">
            فروشگاه هنوز ساخته نشده؛ کالاها بعد از بیلد می‌آیند.
          </p>
        )}
        {hint ? (
          <p className="rounded-xl border border-line px-3 py-2 text-sm leading-7">
            {hint}{" "}
            <Link href="/shop" className="text-warm">
              رفتن به فروشگاه
            </Link>
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          <Input
            className="min-w-40 flex-1"
            value={query}
            placeholder="جستجو"
            onChange={(event) => setQuery(event.target.value)}
          />
          <Button type="button" onClick={() => setEditor("new")}>
            افزودن کالا
          </Button>
        </div>
        {categories.length ? (
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className={`rounded-full border px-3 py-1 text-sm ${category ? "border-line" : "border-accent bg-accent text-onAccent"}`}
              onClick={() => setCategory("")}
            >
              همه
            </button>
            {categories.map((item) => (
              <button
                key={item.title}
                type="button"
                className={`inline-flex min-h-11 items-center rounded-full border px-4 text-sm ${
                  category === item.title ? "border-accent bg-accent text-onAccent" : "border-line"
                }`}
                onClick={() => setCategory(item.title)}
              >
                {item.title}
              </button>
            ))}
          </div>
        ) : null}
        {loading ? (
          <ul className="space-y-2">
            {Array.from({ length: 3 }).map((_, index) => (
              <li key={index} className="h-24 animate-pulse rounded-2xl bg-canvas" />
            ))}
          </ul>
        ) : visible.length === 0 ? (
          <EmptyState
            title={products.length ? "چیزی مطابق جستجو پیدا نشد" : "هنوز کالایی نیست"}
            detail={products.length ? "عبارت دیگری را امتحان کن." : "کانال را وصل کن یا کالا را دستی اضافه کن."}
            action={
              <div className="flex flex-wrap justify-center gap-2">
                <Link
                  href="/more/channels"
                  className="inline-flex min-h-11 items-center rounded-xl bg-accent px-4 text-sm text-onAccent"
                >
                  وصل کردن کانال
                </Link>
                <Button type="button" variant="ghost" onClick={() => setEditor("new")}>
                  افزودن کالا
                </Button>
              </div>
            }
          />
        ) : (
          <ul className="space-y-2">
            {visible.map((product) => {
              const thumb = product.images?.[0] || product.image;
              const discounted = Boolean(product.discount && product.finalPrice);
              const noPhoto = missingPhoto(product);
              const noPrice = missingPrice(product);
              return (
                <li key={product.id}>
                  <Card className="flex cursor-pointer items-start gap-3" onClick={() => setEditor(product)}>
                    {thumb && !noPhoto ? (
                      <AuthImage
                        src={catalogImageUrl(thumb)}
                        alt={product.title}
                        className="h-16 w-16 shrink-0 rounded-lg object-cover"
                      />
                    ) : (
                      <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-lg bg-canvas text-[11px] text-muted">
                        بدون عکس
                      </div>
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="font-medium">{product.title}</p>
                      {noPhoto || noPrice ? (
                        <p className="mt-0.5 flex flex-wrap gap-1 text-[11px]">
                          {noPhoto ? (
                            <span className="rounded-full bg-danger/10 px-2 py-0.5 text-danger">بی‌عکس</span>
                          ) : null}
                          {noPrice ? (
                            <span className="rounded-full bg-danger/10 px-2 py-0.5 text-danger">بی‌قیمت</span>
                          ) : null}
                        </p>
                      ) : null}
                      {product.category || product.subcategory ? (
                        <p className="text-xs text-muted">
                          {[product.category, product.subcategory].filter(Boolean).join(" › ")}
                        </p>
                      ) : null}
                      {product.priceLabel ? (
                        <p className="text-sm">{product.priceLabel}</p>
                      ) : discounted ? (
                        <p className="text-sm">
                          <span className="text-muted line-through">{money(product.price)}</span>{" "}
                          {money(product.finalPrice || 0)} تومان
                        </p>
                      ) : (
                        <p className="text-sm">{priceText(product.price, product.priceLabel)}</p>
                      )}
                      {product.source ? (
                        <p className="text-xs text-warm">
                          از {product.source === "instagram" ? "اینستاگرام" : product.source} {product.sourceHandle || ""}
                        </p>
                      ) : null}
                      <div className="mt-2 flex items-center justify-between gap-3" onClick={(event) => event.stopPropagation()}>
                        <p className="text-sm">موجودی {money(product.stock)}</p>
                        <div className="flex gap-2">
                          <button
                            type="button"
                            className="inline-flex h-11 w-11 items-center justify-center rounded-xl border border-line bg-paper text-lg"
                            disabled={busy || product.stock < 1}
                            onClick={() => void bump(product.id, -1)}
                          >
                            −
                          </button>
                          <button
                            type="button"
                            className="inline-flex h-11 w-11 items-center justify-center rounded-xl border border-accent bg-accent text-lg text-onAccent"
                            disabled={busy}
                            onClick={() => void bump(product.id, 1)}
                          >
                            +
                          </button>
                        </div>
                      </div>
                    </div>
                  </Card>
                </li>
              );
            })}
          </ul>
        )}
      </div>
      {editor !== null ? (
        <ProductEditor
          product={editor === "new" ? null : editor}
          categories={categories}
          onClose={() => setEditor(null)}
          onSaved={(data) => {
            applyCatalog(data, setProducts, setCategories, setShop, setHint);
            setEditor(null);
          }}
          onDeleted={(data) => {
            applyCatalog(data, setProducts, setCategories, setShop, setHint);
            setEditor(null);
          }}
        />
      ) : null}
    </>
  );
}
