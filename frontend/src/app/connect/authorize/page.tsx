import type { Metadata } from "next";
import { Suspense } from "react";

import { SandboxAuthorize } from "@/components/features/connectors/sandbox-authorize";
import { LoadingState } from "@/components/ui/primitives";

export const metadata: Metadata = { title: "Authorize connector (sandbox)" };

export default function Page() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto w-full max-w-md px-4 py-24">
          <LoadingState />
        </div>
      }
    >
      <SandboxAuthorize />
    </Suspense>
  );
}
