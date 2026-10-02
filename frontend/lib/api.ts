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

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`${getApiBase()}${path}`, { ...init, headers });
  if (res.status === 401) {
    clearToken();
    if (typeof window !== "undefined") window.location.href = "/login";
  }
  if (!res.ok) {
    let detail = "خطا";
    try {
      const data = await res.json();
      detail = formatApiDetail(data.detail) || detail;
    } catch {
      detail = res.statusText;
    }
    throw new ApiError(typeof detail === "string" ? detail : "خطا", res.status);
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
