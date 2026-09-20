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
  const msg = err.message.toLowerCase();
  return msg.includes("failed to fetch") || msg.includes("networkerror") || msg.includes("load failed");
}
