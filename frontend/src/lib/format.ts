/**
 * Display formatting. API dates are calendar dates (YYYY-MM-DD, UTC); they are
 * always formatted in UTC so a browser timezone can never shift the day.
 */

export function toNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

const moneyFormatters = new Map<string, Intl.NumberFormat>();

function moneyFormatter(currency: string, compact: boolean, small: boolean): Intl.NumberFormat {
  const key = `${currency}|${compact}|${small}`;
  let formatter = moneyFormatters.get(key);
  if (!formatter) {
    formatter = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      notation: compact ? "compact" : "standard",
      minimumFractionDigits: compact ? 0 : 2,
      maximumFractionDigits: compact ? 1 : small ? 4 : 2,
    });
    moneyFormatters.set(key, formatter);
  }
  return formatter;
}

/** "$1,234.56"; tiny non-zero amounts keep up to 4 decimals so they don't read as $0.00. */
export function formatMoney(
  value: string | number | null | undefined,
  currency: string,
  options: { compact?: boolean } = {},
): string {
  const n = toNumber(value);
  if (n === null) return "—";
  const small = n !== 0 && Math.abs(n) < 0.01;
  try {
    return moneyFormatter(currency, Boolean(options.compact), small).format(n);
  } catch {
    return `${n.toFixed(2)} ${currency}`; // unknown currency code
  }
}

export function formatSignedMoney(value: string | number | null | undefined, currency: string) {
  const n = toNumber(value);
  if (n === null) return "—";
  const text = formatMoney(Math.abs(n), currency);
  return n > 0 ? `+${text}` : n < 0 ? `−${text}` : text;
}

export function formatPct(value: string | number | null | undefined, signed = false): string {
  const n = toNumber(value);
  if (n === null) return "—";
  const text = `${Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 1 })}%`;
  if (!signed) return n < 0 ? `−${text}` : text;
  return n > 0 ? `+${text}` : n < 0 ? `−${text}` : text;
}

export function formatNumber(value: string | number | null | undefined, digits = 2): string {
  const n = toNumber(value);
  if (n === null) return "—";
  return n.toLocaleString("en-US", { maximumFractionDigits: digits });
}

function parseDay(day: string): Date {
  return new Date(`${day}T00:00:00Z`);
}

export function formatDate(day: string | null | undefined, style: "short" | "long" = "long") {
  if (!day) return "—";
  return parseDay(day).toLocaleDateString("en-US", {
    timeZone: "UTC",
    month: "short",
    day: "numeric",
    ...(style === "long" ? { year: "numeric" } : {}),
  });
}

export function formatDateRange(start: string, end: string): string {
  if (start === end) return formatDate(start);
  return `${formatDate(start, "short")} – ${formatDate(end)}`;
}

export function formatMonth(day: string): string {
  return parseDay(day).toLocaleDateString("en-US", {
    timeZone: "UTC",
    month: "short",
    year: "numeric",
  });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Calendar arithmetic on YYYY-MM-DD strings (UTC). */
export function addDays(day: string, days: number): string {
  const date = parseDay(day);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function startOfMonth(day: string): string {
  return `${day.slice(0, 7)}-01`;
}

export const DIMENSION_LABELS: Record<string, string> = {
  total: "Total spend",
  provider: "Provider",
  account_id: "Account",
  service: "Service",
  region: "Region",
  resource_id: "Resource",
  usage_type: "Usage type",
  project: "Project",
  environment: "Environment",
};

export function scopeLabel(scopeType: string, scopeValue: string): string {
  return scopeType === "total" ? "Total spend" : `${DIMENSION_LABELS[scopeType] ?? scopeType}: ${scopeValue}`;
}
