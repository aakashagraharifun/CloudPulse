import { Suspense } from "react";

import { IncidentView } from "@/components/features/incident-view";
import { LoadingState } from "@/components/ui/primitives";

// Rendered client-side behind sign-in (see app/dashboard/layout.tsx), so navigations
// into this page wait for the session check; opt out of instant-navigation validation.
export const instant = false;

export default function IncidentPage() {
  return (
    <Suspense fallback={<LoadingState rows={10} />}>
      <IncidentView />
    </Suspense>
  );
}
