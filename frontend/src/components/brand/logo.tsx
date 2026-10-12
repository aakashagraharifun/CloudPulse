import { cx } from "@/components/ui/primitives";

export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={cx("size-8", className)}>
      <rect width="32" height="32" rx="8" fill="#2a78d6" />
      <path
        d="M5 17h5l3-7 5 13 3-6h6"
        fill="none"
        stroke="#fff"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function Logo({ inverted = false }: { inverted?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2">
      <LogoMark />
      <span
        className={cx(
          "text-base font-semibold tracking-tight",
          inverted ? "text-white" : "text-slate-900",
        )}
      >
        CloudPulse
      </span>
    </span>
  );
}
