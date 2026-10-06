const LOCAL_API = "http://127.0.0.1:8000";

export function getApiBase(): string {
  if (typeof window !== "undefined") {
    const { protocol, hostname } = window.location;
    if (hostname === "app.sozan-core.ir" || hostname === "sozan-core.ir" || hostname === "www.sozan-core.ir" || (hostname.endsWith(".sozan-core.ir") && hostname !== "api.sozan-core.ir")) {
      return `${protocol}//api.sozan-core.ir`;
    }
  }
  return process.env.NEXT_PUBLIC_API_URL || LOCAL_API;
}

/** سیگنال قطع‌شونده برای درخواست‌هایی که نباید روی شبکهٔ کند همیشه منتظر بمانند (مثل بررسی ورود). */
export function timeoutSignal(ms: number): AbortSignal {
  const controller = new AbortController();
  window.setTimeout(() => controller.abort(), ms);
  return controller.signal;
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("sozan_token");
}

export function setToken(token: string) {
  localStorage.setItem("sozan_token", token);
}

export function getOnboarded(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem("sozan_onboarded") === "1";
}

export function setOnboarded(onboarded: boolean) {
  if (onboarded) localStorage.setItem("sozan_onboarded", "1");
  else localStorage.removeItem("sozan_onboarded");
}

export function clearToken() {
  localStorage.removeItem("sozan_token");
  localStorage.removeItem("sozan_onboarded");
}

const DAY_S = 24 * 3600;
let refreshing: Promise<void> | null = null;

function tokenTimes(token: string): { iat: number; exp: number } | null {
  try {
    const body = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    const iat = Number(body.iat);
    const exp = Number(body.exp);
    return Number.isFinite(iat) && Number.isFinite(exp) ? { iat, exp } : null;
  } catch {
    return null;
  }
}

/**
 * ورود تا وقتی فروشنده سر می‌زند بماند: توکنی که بیش از یک روز از ساختش گذشته
 * (یا کمتر از یک هفته مهلت دارد، مثل توکن‌های دوازده‌ساعتهٔ قدیمی) با /auth/refresh تازه می‌شود.
 */
export function refreshSession(): Promise<void> {
  const token = getToken();
  if (!token || refreshing) return refreshing ?? Promise.resolve();
  const times = tokenTimes(token);
  const now = Date.now() / 1000;
  if (times && now - times.iat < DAY_S && times.exp - now > 7 * DAY_S) return Promise.resolve();
  refreshing = api<{ access_token?: string }>("/auth/refresh", { method: "POST", signal: timeoutSignal(15000) })
    .then((data) => {
      if (data.access_token && getToken() === token) setToken(data.access_token);
    })
    .catch(() => undefined)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

function formatApiDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return "";
  const iban = detail.find(
    (row) => row && typeof row === "object" && Array.isArray((row as { loc?: unknown }).loc) && (row as { loc: unknown[] }).loc.includes("iban"),
  );
  if (iban) return "شماره شبا ۲۶ رقم است";
  for (const row of detail) {
    if (row && typeof row === "object" && typeof (row as { msg?: unknown }).msg === "string") {
      return (row as { msg: string }).msg;
    }
  }
  return "";
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const PERSIAN_LETTER = /[\u0600-\u06FF]/;

/** متن فارسی برای خطای HTTP؛ بدنهٔ انگلیسی سرور یا پراکسی («Bad Gateway») به فروشنده نمی‌رسد. */
export function statusMessage(status: number): string {
  if (status === 401) return "نشست تمام شد؛ دوباره وارد شو.";
  if (status === 403) return "اجازهٔ این کار را نداری.";
  if (status === 404) return "پیدا نشد.";
  if (status === 408 || status === 504) return "جواب دیر رسید. دوباره امتحان کن.";
  if (status === 413) return "حجم فایل یا متن بیش از حد است.";
  if (status === 429) return "درخواست‌ها زیاد است؛ چند لحظه صبر کن.";
  if (status >= 500) return "سرور الان جواب نمی‌دهد. چند لحظه بعد دوباره امتحان کن.";
  return "خطایی پیش آمد. دوباره امتحان کن.";
}

/** قطع اینترنت یا زمان‌بر شدن درخواست: status صفر یعنی معلوم نیست سرور درخواست را گرفته یا نه. */
function networkError(err: unknown): ApiError {
  const slow = err instanceof Error && (err.name === "AbortError" || err.name === "TimeoutError");
  return new ApiError(slow ? "جواب دیر رسید. دوباره امتحان کن." : "اینترنت قطع یا ضعیف است. دوباره امتحان کن.", 0);
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  let res: Response;
  try {
    res = await fetch(`${getApiBase()}${path}`, { ...init, headers });
  } catch (err) {
    throw networkError(err);
  }
  if (res.status === 401) {
    clearToken();
    if (typeof window !== "undefined") window.location.href = "/login";
  }
  if (!res.ok) {
    let detail = "";
    try {
      const data = await res.json();
      detail = formatApiDetail(data.detail);
    } catch {
      detail = "";
    }
    throw new ApiError(PERSIAN_LETTER.test(detail) ? detail : statusMessage(res.status), res.status);
  }
  const ctype = res.headers.get("content-type") || "";
  if (ctype.includes("application/json")) return res.json() as Promise<T>;
  return res as unknown as T;
}

export function fileUrl(campaignId: string, relPath: string): string {
  return `${getApiBase()}/campaigns/${campaignId}/file/${relPath}`;
}

export function brandLogoUrl(bust?: number): string {
  const q = bust ? `?t=${bust}` : "";
  return `${getApiBase()}/brand/logo${q}`;
}

export function catalogImageUrl(name: string): string {
  return `${getApiBase()}/catalog/media/${encodeURIComponent(name)}`;
}

export function chatMediaUrl(name: string): string {
  return `${getApiBase()}/chat-media/${encodeURIComponent(name)}`;
}

export type Asset = {
  id: string;
  kind: string;
  channel: string;
  format: string;
  rel_path: string;
};

export type Copy = {
  id: string;
  channel: string;
  format: string;
  body: string;
};

export type Campaign = {
  id: string;
  slug: string;
  pillar: string;
  title: string;
  subtitle: string;
  cta: string;
  assets: Asset[];
  copies: Copy[];
};

export type Brand = {
  name: string;
  description: string;
  has_logo: boolean;
  has_character: boolean;
  has_motion?: boolean;
};
