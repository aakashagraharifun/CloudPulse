import type { Metadata } from "next";

import { AppShell } from "@/components/shell/app-shell";

export const metadata: Metadata = {
  title: "Dashboard",
};

export default function DashboardLayout({ children }: LayoutProps<"/dashboard">) {
  return <AppShell>{children}</AppShell>;
}
