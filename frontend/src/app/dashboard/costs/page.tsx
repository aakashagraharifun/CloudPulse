import type { Metadata } from "next";
import { Suspense } from "react";

import { CostExplorer } from "@/components/features/cost-explorer";
import { LoadingState } from "@/components/ui/primitives";

export const metadata: Metadata = { title: "Cost explorer" };

// Rendered client-side behind sign-in (see app/dashboard/layout.tsx), so navigations
// into this page wait for the session check; opt out of instant-navigation validation.
export const instant = false;

export default function CostsPage() {
  return (
    <Suspense fallback={<LoadingState rows={8} />}>
      <CostExplorer />
    </Suspense>
  );
}
