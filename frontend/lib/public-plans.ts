export type PublicPlan = {
  id: string;
  label: string;
  listPrice: number;
  price: number;
  features: string[];
  checkout: string;
  purchasable: boolean;
};

export type PublicCatalog = {
  discountUntilLabel: string;
  plans: PublicPlan[];
};

export async function loadPublicPlans(): Promise<PublicCatalog | null> {
  const base = (process.env.NEXT_PUBLIC_API_URL || "https://api.sozan-core.ir").replace(/\/$/, "");
  try {
    const response = await fetch(`${base}/billing/plans`, { cache: "no-store" });
    if (!response.ok) return null;
    const body = (await response.json()) as Partial<PublicCatalog>;
    if (!Array.isArray(body.plans)) return null;
    return { discountUntilLabel: body.discountUntilLabel || "", plans: body.plans };
  } catch {
    return null;
  }
}
