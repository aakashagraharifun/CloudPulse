"use client";

import Link from "next/link";
import { Suspense, useState, type ReactNode } from "react";

import { Logo } from "@/components/brand/logo";
import { AuthProvider, useAuth } from "@/components/shell/auth";
import { DataStatusProvider, useDataStatus } from "@/components/shell/data-status";
import { NavLinks, NavLinksFallback } from "@/components/shell/nav";
import { Badge, Button, cx, inputClass } from "@/components/ui/primitives";
import { errorMessage } from "@/lib/api";
import { formatDate } from "@/lib/format";

function DataStatusBar() {
  const { status, loading, error, currency, setCurrency } = useDataStatus();

  if (error) {
    return (
      <p role="alert" className="truncate text-xs text-red-700">
        {errorMessage(error)}
      </p>
    );
  }
  if (loading && !status) return <p className="text-xs text-slate-500">Checking data…</p>;
  if (!status?.has_data) {
    return (
      <p className="text-xs text-slate-600">
        No billing data yet.{" "}
        <Link href="/dashboard/imports" className="font-medium text-brand-700 hover:underline">
          Import data
        </Link>
      </p>
    );
  }
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
      {status.has_sample_data && (
        <Badge tone="sample">
          <span aria-hidden>◆</span> Sample data
        </Badge>
      )}
      <span className="hidden text-xs text-slate-600 sm:inline">
        Data {formatDate(status.data_start, "short")} – {formatDate(status.data_end)}
      </span>
      {status.currencies.length > 1 && currency && (
        <label className="flex items-center gap-2 text-xs text-slate-600">
          Currency
          <select
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            className={cx(inputClass, "h-8 w-24 py-0")}
          >
            {status.currencies.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
      )}
      {status.currencies.length === 1 && (
        <span className="hidden text-xs text-slate-500 md:inline">Currency: {currency}</span>
      )}
    </div>
  );
}

function UserBlock() {
  const { user, signOut } = useAuth();
  const [busy, setBusy] = useState(false);
  return (
    <div className="rounded-lg bg-slate-50 p-3">
      <p className="truncate text-sm font-medium text-slate-900" title={user.email}>
        {user.name}
      </p>
      <p className="truncate text-xs text-slate-500">{user.email}</p>
      <div className="mt-2 flex items-center justify-between gap-2">
        <Badge tone={user.role === "admin" ? "brand" : "neutral"} className="capitalize">
          {user.role}
        </Badge>
        <Button
          variant="ghost"
          size="sm"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            void signOut();
          }}
        >
          {busy ? "Signing out…" : "Sign out"}
        </Button>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <Shell>{children}</Shell>
    </AuthProvider>
  );
}

function Shell({ children }: { children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <DataStatusProvider>
      <div className="flex min-h-screen bg-slate-50">
        <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-slate-200 bg-white px-4 py-5 lg:flex">
          <Link href="/" className="mb-8 px-2" aria-label="CloudPulse home">
            <Logo />
          </Link>
          <nav aria-label="Main">
            <Suspense fallback={<NavLinksFallback />}>
              <NavLinks />
            </Suspense>
          </nav>
          <div className="mt-auto">
            <UserBlock />
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur">
            <div className="flex h-14 items-center gap-3 px-4 sm:px-6">
              <button
                type="button"
                className="rounded-lg p-2 text-slate-700 hover:bg-slate-100 lg:hidden"
                aria-label={menuOpen ? "Close menu" : "Open menu"}
                aria-expanded={menuOpen}
                aria-controls="mobile-nav"
                onClick={() => setMenuOpen((open) => !open)}
              >
                <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d={menuOpen ? "M6 6l12 12M18 6L6 18" : "M4 7h16M4 12h16M4 17h16"} strokeLinecap="round" />
                </svg>
              </button>
              <Link href="/" className="lg:hidden" aria-label="CloudPulse home">
                <Logo />
              </Link>
              <div className="ml-auto min-w-0 lg:ml-0">
                <DataStatusBar />
              </div>
            </div>
            {menuOpen && (
              <nav id="mobile-nav" aria-label="Main" className="border-t border-slate-200 px-4 py-3 lg:hidden">
                <Suspense fallback={<NavLinksFallback />}>
                  <NavLinks onNavigate={() => setMenuOpen(false)} />
                </Suspense>
                <div className="mt-3">
                  <UserBlock />
                </div>
              </nav>
            )}
          </header>
          <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 lg:py-8">{children}</main>
        </div>
      </div>
    </DataStatusProvider>
  );
}
