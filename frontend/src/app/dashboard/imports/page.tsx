import type { Metadata } from "next";

import { ImportsPage } from "@/components/features/imports-page";

export const metadata: Metadata = { title: "Imports" };

// Rendered client-side behind sign-in (see app/dashboard/layout.tsx), so navigations
// into this page wait for the session check; opt out of instant-navigation validation.
export const instant = false;

export default function Page() {
  return <ImportsPage />;
}
