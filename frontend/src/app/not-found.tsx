import Link from "next/link";

import { Logo } from "@/components/brand/logo";
import { buttonClass } from "@/components/ui/primitives";

export default function NotFound() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-4 px-4 py-24 text-center">
      <Logo />
      <h1 className="text-2xl font-semibold text-slate-900">Page not found</h1>
      <p className="max-w-md text-slate-600">The page you were looking for does not exist.</p>
      <div className="flex gap-2">
        <Link href="/" className={buttonClass("secondary")}>
          Home
        </Link>
        <Link href="/dashboard" className={buttonClass("primary")}>
          Dashboard
        </Link>
      </div>
    </main>
  );
}
