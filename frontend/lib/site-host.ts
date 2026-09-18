export function hostName(hostHeader: string | null): string {
  return (hostHeader || "").split(":")[0].toLowerCase();
}

export function isPanelHost(hostHeader: string | null): boolean {
  return hostName(hostHeader) === "app.sozan-core.ir";
}

export function panelOriginFromHost(hostHeader: string | null): string {
  const name = hostName(hostHeader);
  if (name === "sozan-core.ir" || name === "www.sozan-core.ir") {
    return "https://app.sozan-core.ir";
  }
  return "";
}
