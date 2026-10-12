"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, useSyncExternalStore, type FormEvent } from "react";

import { Logo } from "@/components/brand/logo";
import { Button, ErrorState, Field, LoadingState, Notice, inputClass } from "@/components/ui/primitives";
import { api, errorMessage, type SessionResponse } from "@/lib/api";
import { authToken, safeNextPath } from "@/lib/auth-token";
import { useApi } from "@/lib/hooks";

export function LoginView() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNextPath(params.get("next"));
  const token = useSyncExternalStore(authToken.subscribe, authToken.get, () => null);
  const status = useApi<{ setup_required: boolean }>("/auth/status");

  // Already signed in (e.g. the back button): continue to the app.
  useEffect(() => {
    if (token) router.replace(next);
  }, [token, next, router]);

  return (
    <main className="flex flex-1 flex-col items-center justify-center bg-slate-50 px-4 py-16">
      <Link href="/" className="mb-8" aria-label="CloudPulse home">
        <Logo />
      </Link>
      <div className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        {status.error ? (
          <ErrorState message={errorMessage(status.error)} onRetry={status.reload} />
        ) : !status.data ? (
          <LoadingState />
        ) : (
          <SignInForm setup={status.data.setup_required} onSignedIn={() => router.replace(next)} />
        )}
      </div>
      <p className="mt-6 max-w-sm text-center text-xs text-slate-500">
        Forgot your password? An admin can reset it under Settings → Users, or run{" "}
        <code className="font-mono">python -m scripts.manage_users reset-password</code> on the server.
      </p>
    </main>
  );
}

function SignInForm({ setup, onSignedIn }: { setup: boolean; onSignedIn: () => void }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (setup && password !== confirm) {
      setError("The passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      const session = setup
        ? await api.post<SessionResponse>("/auth/setup", { name, email, password })
        : await api.post<SessionResponse>("/auth/login", { email, password });
      authToken.set(session.token);
      onSignedIn();
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-slate-900">
          {setup ? "Create the admin account" : "Sign in to CloudPulse"}
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          {setup
            ? "No users exist yet. The first account becomes the workspace admin."
            : "Use the account your CloudPulse admin created for you."}
        </p>
      </div>
      {setup && (
        <Field label="Name" htmlFor="name">
          <input id="name" required maxLength={80} autoComplete="name" className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
      )}
      <Field label="Email" htmlFor="email">
        <input
          id="email"
          type="email"
          required
          maxLength={254}
          autoComplete={setup ? "email" : "username"}
          className={inputClass}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </Field>
      <Field label="Password" htmlFor="password" hint={setup ? "At least 10 characters." : undefined}>
        <input
          id="password"
          type="password"
          required
          minLength={setup ? 10 : 1}
          maxLength={128}
          autoComplete={setup ? "new-password" : "current-password"}
          className={inputClass}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </Field>
      {setup && (
        <Field label="Confirm password" htmlFor="confirm">
          <input
            id="confirm"
            type="password"
            required
            maxLength={128}
            autoComplete="new-password"
            className={inputClass}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
        </Field>
      )}
      {error && <Notice tone="error">{error}</Notice>}
      <Button type="submit" className="w-full" disabled={busy}>
        {busy ? (setup ? "Creating account…" : "Signing in…") : setup ? "Create admin account" : "Sign in"}
      </Button>
    </form>
  );
}
