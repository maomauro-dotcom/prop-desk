const usdFmt = new Intl.NumberFormat("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pxFmt = new Intl.NumberFormat("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const usd = (v: number | null | undefined) => (v == null ? "—" : `${usdFmt.format(v)} USD`);
export const signedUsd = (v: number | null | undefined) =>
  v == null ? "—" : `${v > 0 ? "+" : ""}${usdFmt.format(v)} USD`;
export const px = (v: number | null | undefined) => (v == null ? "—" : pxFmt.format(v));
export const pct = (v: number | null | undefined) => (v == null ? "—" : `${v.toFixed(1)} %`);

/** "2026-10-05T09:46:00-04:00" -> "10-05 09:46" (keeps the ET wall time from the ISO string). */
export function etTime(iso: string | null | undefined, withDate = true): string {
  if (!iso) return "—";
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!m) return iso;
  return withDate ? `${m[2]}-${m[3]} ${m[4]}:${m[5]}` : `${m[4]}:${m[5]}`;
}

export const STRATEGY_LABEL: Record<string, string> = {
  orb: "ORB",
  vwap_reclaim: "VWAP",
  liquidity_sweep: "Sweep",
};

export const SIDE_LABEL: Record<string, string> = { long: "Compra", short: "Venta" };
