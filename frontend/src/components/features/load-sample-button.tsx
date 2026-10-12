"use client";

import { useState } from "react";

import { useDataStatus } from "@/components/shell/data-status";
import { Button } from "@/components/ui/primitives";
import { api, errorMessage, type ImportDetail } from "@/lib/api";

/** Loads the built-in synthetic dataset (clearly marked as sample data). */
export function LoadSampleButton({
  variant = "primary",
  onLoaded,
}: {
  variant?: "primary" | "secondary";
  onLoaded?: (result: ImportDetail) => void;
}) {
  const { refresh } = useDataStatus();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setBusy(true);
    setError(null);
    try {
      const result = await api.post<ImportDetail>("/imports/sample");
      refresh();
      onLoaded?.(result);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-center gap-2">
      <Button variant={variant} onClick={load} disabled={busy}>
        {busy ? "Loading sample data…" : "Load sample data"}
      </Button>
      {error && (
        <p role="alert" className="max-w-sm text-center text-xs text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}
