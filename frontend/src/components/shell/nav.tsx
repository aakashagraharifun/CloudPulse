"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cx } from "@/components/ui/primitives";

export const NAV_ITEMS = [
  { href: "/dashboard", label: "Overview", icon: "M3 12l9-8 9 8M5 10v10h14V10" },
  { href: "/dashboard/costs", label: "Cost explorer", icon: "M4 19V5m0 14h16M8 15l3-4 3 2 5-6" },
  {
    href: "/dashboard/incidents",
    label: "Incidents",
    icon: "M12 9v4m0 4h.01M10.3 3.9L2.4 17.5A2 2 0 004.1 20.5h15.8a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z",
  },
  { href: "/dashboard/budgets", label: "Budgets", icon: "M12 3v18m4-14H10a3 3 0 000 6h4a3 3 0 010 6H7" },
  { href: "/dashboard/imports", label: "Imports", icon: "M12 15V3m0 12l-4-4m4 4l4-4M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2" },
  {
    href: "/dashboard/connectors",
    label: "Connectors",
    icon: "M12 22v-5M9 8V2m6 6V2m3 6v5a4 4 0 01-4 4h-4a4 4 0 01-4-4V8z",
  },
  {
    href: "/dashboard/settings",
    label: "Settings",
    icon: "M10.3 4.3a1.7 1.7 0 013.4 0 1.7 1.7 0 002.6 1.1 1.7 1.7 0 012.4 2.4 1.7 1.7 0 001.1 2.6 1.7 1.7 0 010 3.4 1.7 1.7 0 00-1.1 2.6 1.7 1.7 0 01-2.4 2.4 1.7 1.7 0 00-2.6 1.1 1.7 1.7 0 01-3.4 0 1.7 1.7 0 00-2.6-1.1 1.7 1.7 0 01-2.4-2.4 1.7 1.7 0 00-1.1-2.6 1.7 1.7 0 010-3.4 1.7 1.7 0 001.1-2.6 1.7 1.7 0 012.4-2.4 1.7 1.7 0 002.6-1.1zM12 15a3 3 0 100-6 3 3 0 000 6z",
  },
] as const;

function isActive(pathname: string, href: string) {
  return href === "/dashboard" ? pathname === href : pathname.startsWith(href);
}

export function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <ul className="space-y-1">
      {NAV_ITEMS.map((item) => {
        const active = isActive(pathname, item.href);
        return (
          <li key={item.href}>
            <Link
              href={item.href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={cx(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "bg-brand-50 text-brand-700"
                  : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
              )}
            >
              <svg
                viewBox="0 0 24 24"
                aria-hidden
                className="size-4.5 shrink-0"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d={item.icon} />
              </svg>
              {item.label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

/** Static fallback while the pathname is resolved (keeps the layout prerenderable). */
export function NavLinksFallback() {
  return (
    <ul className="space-y-1">
      {NAV_ITEMS.map((item) => (
        <li key={item.href}>
          <Link
            href={item.href}
            className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-600"
          >
            <span className="size-4.5" aria-hidden />
            {item.label}
          </Link>
        </li>
      ))}
    </ul>
  );
}
