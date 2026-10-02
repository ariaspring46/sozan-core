export type IdempotencySlot = { key: string; stamp: string };

export function emptyIdempotencySlot(): IdempotencySlot {
  return { key: "", stamp: "" };
}

export function takeIdempotencyKey(slot: IdempotencySlot, stamp: string): string {
  if (slot.key && slot.stamp === stamp) return slot.key;
  slot.key = crypto.randomUUID();
  slot.stamp = stamp;
  return slot.key;
}

export function finishIdempotencyKey(slot: IdempotencySlot, err?: unknown): void {
  if (err !== undefined && isUncertainNetworkError(err)) return;
  slot.key = "";
  slot.stamp = "";
}

export function isUncertainNetworkError(err: unknown): boolean {
  if (!(err instanceof Error)) return true;
  if (err.name === "AbortError" || err.name === "TypeError") return true;
  const status = "status" in err ? Number((err as { status?: number }).status) : 0;
  // status 0 = api() could not reach the server (offline or timed out): the request may still have landed.
  if (err.name === "ApiError" && status === 0) return true;
  if (status === 408 || status === 409 || status === 502 || status === 503 || status === 504) return true;
  const msg = err.message.toLowerCase();
  return msg.includes("failed to fetch") || msg.includes("networkerror") || msg.includes("load failed");
}
