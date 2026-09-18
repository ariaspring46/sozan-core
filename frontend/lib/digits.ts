const DIGIT_MAP: Record<string, string> = {
  "۰": "0",
  "۱": "1",
  "۲": "2",
  "۳": "3",
  "۴": "4",
  "۵": "5",
  "۶": "6",
  "۷": "7",
  "۸": "8",
  "۹": "9",
  "٠": "0",
  "١": "1",
  "٢": "2",
  "٣": "3",
  "٤": "4",
  "٥": "5",
  "٦": "6",
  "٧": "7",
  "٨": "8",
  "٩": "9",
};

export function toLatinDigits(raw: string): string {
  return [...(raw || "")].map((ch) => DIGIT_MAP[ch] ?? ch).join("");
}

/** Non-negative integer from Persian/Arabic/Latin digits. Empty or junk → null. */
export function parseNonNegativeInt(raw: string): number | null {
  const cleaned = toLatinDigits(raw).replace(/[,\s_\u066C]/g, "");
  if (!cleaned) return null;
  if (!/^\d+$/.test(cleaned)) return null;
  const value = Number(cleaned);
  if (!Number.isSafeInteger(value) || value < 0) return null;
  return value;
}

export function money(amount: number): string {
  return new Intl.NumberFormat("fa-IR").format(amount);
}

export function priceText(price: number, label?: string): string {
  if (label) return label;
  if (!price) return "تماس بگیرید";
  return `${money(price)} تومان`;
}

export function formatWhen(at: number): string {
  if (!at) return "";
  const ms = at > 1e12 ? at : at * 1000;
  return new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(ms));
}
