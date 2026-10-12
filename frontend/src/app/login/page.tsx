import type { Metadata } from "next";
import { Suspense } from "react";

import { LoginView } from "@/components/features/login-view";
import { LoadingState } from "@/components/ui/primitives";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto w-full max-w-md px-4 py-24">
          <LoadingState />
        </div>
      }
    >
      <LoginView />
    </Suspense>
  );
}
