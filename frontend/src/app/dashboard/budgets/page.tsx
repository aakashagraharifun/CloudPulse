import type { Metadata } from "next";

import { BudgetsPage } from "@/components/features/budgets-page";

export const metadata: Metadata = { title: "Budgets" };

// Rendered client-side behind sign-in (see app/dashboard/layout.tsx), so navigations
// into this page wait for the session check; opt out of instant-navigation validation.
export const instant = false;

export default function Page() {
  return <BudgetsPage />;
}
