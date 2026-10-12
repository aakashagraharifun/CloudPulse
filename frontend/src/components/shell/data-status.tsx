"use client";

import { createContext, useContext, type ReactNode } from "react";

import type { DataStatus } from "@/lib/api";
import { useApi, useStoredValue } from "@/lib/hooks";

type DataStatusContext = {
  status: DataStatus | undefined;
  loading: boolean;
  error: unknown;
  /** Currency currently analysed; null when there is no data. */
  currency: string | null;
  setCurrency: (currency: string) => void;
  refresh: () => void;
};

const Context = createContext<DataStatusContext | null>(null);

export function DataStatusProvider({ children }: { children: ReactNode }) {
  const { data, loading, error, reload } = useApi<DataStatus>("/costs/data-status");
  const [stored, setStored] = useStoredValue("cloudpulse.currency", "");

  // The stored choice wins only while that currency still exists in the data.
  const currency =
    data && data.currencies.includes(stored) ? stored : (data?.default_currency ?? null);

  return (
    <Context.Provider
      value={{ status: data, loading, error, currency, setCurrency: setStored, refresh: reload }}
    >
      {children}
    </Context.Provider>
  );
}

export function useDataStatus(): DataStatusContext {
  const value = useContext(Context);
  if (!value) throw new Error("useDataStatus must be used inside DataStatusProvider");
  return value;
}
