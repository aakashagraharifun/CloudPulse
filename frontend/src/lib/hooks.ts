"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

import { api } from "@/lib/api";

type Result<T> = {
  path: string | null;
  version: number;
  data?: T;
  error?: unknown;
};

export type ApiState<T> = {
  /** Latest successful data (kept while a refresh is in flight). */
  data: T | undefined;
  error: unknown;
  loading: boolean;
  reload: () => void;
};

/**
 * Fetch `path` from the API whenever it (or the reload counter) changes.
 * Pass `null` to skip fetching. Loading is derived rather than stored, so no
 * state is set synchronously inside the effect.
 */
export function useApi<T>(path: string | null): ApiState<T> {
  const [version, setVersion] = useState(0);
  const [result, setResult] = useState<Result<T>>({ path: null, version: -1 });

  useEffect(() => {
    if (path === null) return;
    const controller = new AbortController();
    api.get<T>(path, controller.signal).then(
      (data) => setResult({ path, version, data }),
      (error: unknown) => {
        if (!controller.signal.aborted) setResult((prev) => ({ ...prev, path, version, error }));
      },
    );
    return () => controller.abort();
  }, [path, version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  const current = result.path === path && result.version === version;
  return {
    data: result.data,
    error: current ? result.error : undefined,
    loading: path !== null && !current,
    reload,
  };
}

// --- localStorage-backed preferences (SSR-safe) ---------------------------------

const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null; // storage blocked (private mode, policies)
  }
}

/** A string preference persisted in localStorage; `fallback` on the server and first render. */
export function useStoredValue(key: string, fallback: string): [string, (value: string) => void] {
  const value = useSyncExternalStore(
    subscribe,
    () => readStorage(key) ?? fallback,
    () => fallback,
  );
  const setValue = useCallback(
    (next: string) => {
      try {
        window.localStorage.setItem(key, next);
      } catch {
        // ignore: the value simply won't persist
      }
      listeners.forEach((listener) => listener());
    },
    [key],
  );
  return [value, setValue];
}
