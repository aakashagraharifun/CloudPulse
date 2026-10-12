import Link from "next/link";
import type { ButtonHTMLAttributes, ComponentProps, ReactNode } from "react";

function cx(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}
export { cx };

// --- Button ------------------------------------------------------------------

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-700 disabled:bg-brand-600/50",
  secondary:
    "border border-slate-300 bg-white text-slate-800 hover:bg-slate-50 disabled:text-slate-400",
  ghost: "text-slate-700 hover:bg-slate-100 disabled:text-slate-400",
  danger: "border border-red-200 bg-white text-red-700 hover:bg-red-50 disabled:text-red-300",
};
const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-xs",
  md: "h-9 px-4 text-sm",
};

export function buttonClass(variant: Variant = "primary", size: Size = "md") {
  return cx(
    "inline-flex shrink-0 items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:cursor-not-allowed",
    VARIANTS[variant],
    SIZES[size],
  );
}

export function Button({
  variant = "primary",
  size = "md",
  className,
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }) {
  return <button type={type} className={cx(buttonClass(variant, size), className)} {...props} />;
}

export function ButtonLink({
  variant = "primary",
  size = "md",
  className,
  ...props
}: ComponentProps<typeof Link> & { variant?: Variant; size?: Size }) {
  return <Link className={cx(buttonClass(variant, size), className)} {...props} />;
}

// --- Card --------------------------------------------------------------------

export function Card({
  title,
  description,
  action,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={cx("min-w-0 rounded-xl border border-slate-200 bg-white", className)}>
      {(title || action) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold text-slate-900">{title}</h2>}
            {description && <p className="mt-0.5 text-xs text-slate-500">{description}</p>}
          </div>
          {action && <div className="flex flex-wrap items-center gap-2">{action}</div>}
        </header>
      )}
      <div className={cx("p-5", bodyClassName)}>{children}</div>
    </section>
  );
}

// --- Badges ------------------------------------------------------------------

export function Badge({
  children,
  tone = "neutral",
  className,
}: {
  children: ReactNode;
  tone?: "neutral" | "brand" | "good" | "warning" | "serious" | "critical" | "sample";
  className?: string;
}) {
  const tones = {
    neutral: "bg-slate-100 text-slate-700 ring-slate-200",
    brand: "bg-brand-50 text-brand-700 ring-brand-100",
    good: "bg-green-50 text-good-text ring-green-200",
    warning: "bg-amber-50 text-amber-800 ring-amber-200",
    serious: "bg-orange-50 text-orange-800 ring-orange-200",
    critical: "bg-red-50 text-red-700 ring-red-200",
    sample: "bg-violet-50 text-violet-800 ring-violet-200",
  };
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

const SEVERITY_STYLE = {
  low: { tone: "neutral", dot: "bg-slate-400", label: "Low" },
  medium: { tone: "warning", dot: "bg-warning", label: "Medium" },
  high: { tone: "serious", dot: "bg-serious", label: "High" },
  critical: { tone: "critical", dot: "bg-critical", label: "Critical" },
} as const;

export function SeverityBadge({ severity }: { severity: keyof typeof SEVERITY_STYLE }) {
  const style = SEVERITY_STYLE[severity];
  return (
    <Badge tone={style.tone}>
      <span aria-hidden className={cx("size-1.5 rounded-full", style.dot)} />
      {style.label}
    </Badge>
  );
}

export function StatusBadge({ status }: { status: "open" | "acknowledged" | "resolved" }) {
  const map = {
    open: { tone: "critical", label: "Open" },
    acknowledged: { tone: "warning", label: "Acknowledged" },
    resolved: { tone: "good", label: "Resolved" },
  } as const;
  return <Badge tone={map[status].tone}>{map[status].label}</Badge>;
}

// --- Stat tile -----------------------------------------------------------------

export function StatTile({
  label,
  value,
  delta,
  hint,
}: {
  label: string;
  value: ReactNode;
  delta?: { text: string; direction: "up" | "down" | "flat"; goodWhen: "up" | "down" } | null;
  hint?: ReactNode;
}) {
  const good =
    delta && delta.direction !== "flat" && delta.direction === delta.goodWhen ? true : false;
  const deltaClass = !delta
    ? ""
    : delta.direction === "flat"
      ? "text-slate-500"
      : good
        ? "text-good-text"
        : "text-red-700";
  return (
    <div className="min-w-0 rounded-xl border border-slate-200 bg-white p-5">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <div className="mt-2 truncate text-2xl font-semibold tracking-tight text-slate-900">
        {value}
      </div>
      {(delta || hint) && (
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 text-xs">
          {delta && (
            <span className={cx("font-medium", deltaClass)}>
              {delta.direction === "up" ? "▲" : delta.direction === "down" ? "▼" : "■"}{" "}
              {delta.text}
            </span>
          )}
          {hint && <span className="text-slate-500">{hint}</span>}
        </div>
      )}
    </div>
  );
}

// --- States ------------------------------------------------------------------

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded-md bg-slate-100", className)} />;
}

export function LoadingState({ rows = 3, label = "Loading…" }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-live="polite" className="space-y-3">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={i === 0 ? "h-5 w-1/3" : "h-4 w-full"} />
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-4 py-10 text-center">
      <div
        aria-hidden
        className="mb-3 flex size-10 items-center justify-center rounded-full bg-slate-100 text-slate-400"
      >
        <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M3 12h4l3 7 4-14 3 7h4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
      <p className="text-sm font-semibold text-slate-900">{title}</p>
      {description && <p className="mt-1 max-w-md text-sm text-slate-600">{description}</p>}
      {action && <div className="mt-4 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4 sm:flex-row sm:items-center sm:justify-between"
    >
      <p className="text-sm text-red-800">
        <span className="font-semibold">Couldn’t load this data.</span> {message}
      </p>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}

export function Notice({
  tone = "info",
  children,
}: {
  tone?: "info" | "success" | "warning" | "error";
  children: ReactNode;
}) {
  const tones = {
    info: "border-brand-100 bg-brand-50 text-brand-800",
    success: "border-green-200 bg-green-50 text-good-text",
    warning: "border-amber-200 bg-amber-50 text-amber-900",
    error: "border-red-200 bg-red-50 text-red-800",
  };
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cx("rounded-lg border px-4 py-3 text-sm", tones[tone])}
    >
      {children}
    </div>
  );
}

// --- Meter -------------------------------------------------------------------

export function Meter({ value, label }: { value: number | null; label: string }) {
  const pct = value === null ? 0 : Math.max(0, Math.min(100, value));
  const tone =
    value === null
      ? "bg-slate-300"
      : value >= 100
        ? "bg-critical"
        : value >= 80
          ? "bg-warning"
          : "bg-brand-600";
  const track =
    value !== null && value >= 100 ? "bg-red-100" : value !== null && value >= 80 ? "bg-amber-100" : "bg-brand-100";
  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value === null ? undefined : Math.round(value)}
      className={cx("h-2 w-full overflow-hidden rounded-full", track)}
    >
      <div className={cx("h-full rounded-full", tone)} style={{ width: `${pct}%` }} />
    </div>
  );
}

// --- Forms -------------------------------------------------------------------

export const inputClass =
  "block h-9 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-600/20 disabled:bg-slate-50";

export function Field({
  label,
  htmlFor,
  hint,
  children,
  className,
}: {
  label: string;
  htmlFor: string;
  hint?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cx("min-w-0", className)}>
      <label htmlFor={htmlFor} className="mb-1 block text-xs font-medium text-slate-700">
        {label}
      </label>
      {children}
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-slate-600">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Pagination({
  total,
  limit,
  offset,
  onChange,
}: {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
}) {
  if (total <= limit) return null;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);
  return (
    <nav aria-label="Pagination" className="flex items-center justify-between gap-3 pt-4 text-sm">
      <span className="text-slate-600">
        {offset + 1}–{Math.min(offset + limit, total)} of {total}
      </span>
      <div className="flex items-center gap-2">
        <Button
          variant="secondary"
          size="sm"
          disabled={page <= 1}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          Previous
        </Button>
        <span className="text-slate-600">
          Page {page} of {pages}
        </span>
        <Button
          variant="secondary"
          size="sm"
          disabled={page >= pages}
          onClick={() => onChange(offset + limit)}
        >
          Next
        </Button>
      </div>
    </nav>
  );
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cx("font-mono text-[0.8125rem]", className)}>{children}</span>;
}
