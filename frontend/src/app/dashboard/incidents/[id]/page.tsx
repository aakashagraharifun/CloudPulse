import { Suspense } from "react";

import { IncidentView } from "@/components/features/incident-view";
import { LoadingState } from "@/components/ui/primitives";

export default function IncidentPage() {
  return (
    <Suspense fallback={<LoadingState rows={10} />}>
      <IncidentView />
    </Suspense>
  );
}
