import type { Metadata } from "next";
import { Suspense } from "react";

import { CostExplorer } from "@/components/features/cost-explorer";
import { LoadingState } from "@/components/ui/primitives";

export const metadata: Metadata = { title: "Cost explorer" };

export default function CostsPage() {
  return (
    <Suspense fallback={<LoadingState rows={8} />}>
      <CostExplorer />
    </Suspense>
  );
}
