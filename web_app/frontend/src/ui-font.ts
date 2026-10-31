// Presentation preference shared by the architecture and converter workspaces.
export const FONT_SIZES = Array.from({ length: 15 }, (_, i) => 12 + i * 2);
export function normalizeFontSize(value: unknown, fallback = 16): number {
  const n = Number(value);
  return Number.isFinite(n) && n > 0
    ? Math.max(12, Math.min(40, 12 + 2 * Math.round((n - 12) / 2)))
    : fallback;
}
