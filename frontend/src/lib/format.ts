export function percent(value: number | undefined): string {
  return `${Math.round((value ?? 0) * 100)}%`;
}

export function count(value: number | undefined): string {
  return String(Math.round(value ?? 0));
}

export function oneDecimal(value: number | undefined): string {
  return (value ?? 0).toFixed(1);
}

export function minutes(value: number | undefined): string {
  const total = Math.round(value ?? 0);
  if (total < 60) return `${total}m`;
  const hours = Math.floor(total / 60);
  return `${hours}h ${total % 60}m`;
}

export function shortDate(iso: string): string {
  // `new Date("2026-09-07")` is parsed as UTC midnight, which renders as the
  // previous day anywhere west of Greenwich. Rollup periods are plain dates,
  // so build them from their own parts instead.
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

/** Toil bands: below 35 is healthy, 65 and above needs attention this week. */
export function toilTone(score: number): "calm" | "warn" | "alarm" {
  if (score >= 65) return "alarm";
  if (score >= 35) return "warn";
  return "calm";
}

export const TONE_TEXT: Record<string, string> = {
  calm: "text-teal-700",
  warn: "text-amber-700",
  alarm: "text-red-700",
};

export const TONE_BG: Record<string, string> = {
  calm: "bg-teal-50 border-teal-200",
  warn: "bg-amber-50 border-amber-200",
  alarm: "bg-red-50 border-red-200",
};

export const TONE_STROKE: Record<string, string> = {
  calm: "#0d9488",
  warn: "#d97706",
  alarm: "#dc2626",
};
