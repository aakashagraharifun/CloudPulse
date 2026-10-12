import type { Metadata } from "next";

import { OverviewPage } from "@/components/features/overview-page";

export const metadata: Metadata = { title: "Overview" };

// Rendered client-side behind sign-in (see app/dashboard/layout.tsx), so navigations
// into this page wait for the session check; opt out of instant-navigation validation.
export const instant = false;

export default function Page() {
  return <OverviewPage />;
}
