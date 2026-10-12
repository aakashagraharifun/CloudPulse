import type { Metadata } from "next";

import { AppShell } from "@/components/shell/app-shell";

export const metadata: Metadata = {
  title: "Dashboard",
};

// The dashboard is client-rendered behind sign-in: the session token lives in the
// browser, so the static shell can only show "Checking your session…" and the
// pages load their data client-side. Navigations into it are expected to wait for
// that, so opt the dashboard out of instant-navigation validation.
export const instant = false;

export default function DashboardLayout({ children }: LayoutProps<"/dashboard">) {
  return <AppShell>{children}</AppShell>;
}
