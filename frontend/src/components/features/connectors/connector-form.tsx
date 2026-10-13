"use client";

import { ExternalLinkIcon, FlaskConicalIcon, KeyRoundIcon, ShieldCheckIcon } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { ProviderMark } from "@/components/features/connectors/flow-stage";
import { VerifyFlow } from "@/components/features/connectors/verify-flow";
import { Button, Card, Field, Notice, cx, inputClass } from "@/components/ui/primitives";
import {
  api,
  errorMessage,
  type CatalogEntry,
  type CatalogField,
  type Connector,
  type ConnectorSettingsInput,
  type SandboxAuthMessage,
  type VerifyResponse,
} from "@/lib/api";

type Value = string | number | boolean;
type Mode = "sandbox" | "live";
type VerifyState = { phase: "idle" | "verifying" | "done"; result: VerifyResponse | null };

const INTERVALS = [
  { value: 0, label: "Manual only" },
  { value: 6, label: "Every 6 hours" },
  { value: 12, label: "Every 12 hours" },
  { value: 24, label: "Daily" },
  { value: 168, label: "Weekly" },
];

function initialValues(entry: CatalogEntry, existing: Connector | null): Record<string, Value> {
  const values: Record<string, Value> = {};
  for (const field of entry.fields) {
    const stored = field.secret ? undefined : existing?.config[field.key];
    const value = stored ?? field.default;
    values[field.key] =
      value === null || value === undefined ? (field.type === "toggle" ? false : "") : (value as Value);
  }
  return values;
}

function visible(field: CatalogField, values: Record<string, Value>) {
  return !field.show_if || String(values[field.show_if.key]) === field.show_if.value;
}

/** Split the form into the non-secret config and the (write-only) credentials. */
function payloadParts(entry: CatalogEntry, values: Record<string, Value>, mode: Mode, sandboxToken: string | null) {
  const config: Record<string, unknown> = {};
  const credentials: Record<string, string> = {};
  for (const field of entry.fields) {
    if (!visible(field, values) || (mode === "sandbox" && field.section === "auth")) continue;
    const raw = values[field.key];
    if (field.secret) {
      if (typeof raw === "string" && raw.trim()) credentials[field.key] = raw.trim();
      continue;
    }
    if (field.type === "toggle") config[field.key] = Boolean(raw);
    else if (field.type === "number") config[field.key] = raw === "" ? undefined : Number(raw);
    else if (typeof raw === "string" && raw.trim()) config[field.key] = raw.trim();
  }
  if (mode === "sandbox" && sandboxToken) credentials.sandbox_token = sandboxToken;
  return { config, credentials };
}

function sandboxResult(identity: string): VerifyResponse {
  return {
    ok: true,
    identity,
    steps: [
      { key: "authenticate", label: "Authorize the sandbox account", status: "ok", detail: `Access token accepted for ${identity}.` },
      { key: "permission", label: "Read billing data", status: "ok", detail: "Read-only access to the simulated cost API is granted." },
    ],
  };
}

export function ConnectorForm({
  entry,
  existing,
  onCancel,
  onSaved,
}: {
  entry: CatalogEntry;
  existing: Connector | null;
  onCancel: () => void;
  onSaved: (connector: Connector, created: boolean) => void;
}) {
  const [name, setName] = useState(existing?.name ?? entry.name);
  const [values, setValues] = useState<Record<string, Value>>(() => initialValues(entry, existing));
  const [interval, setSyncInterval] = useState(existing?.sync_interval_hours ?? 24);
  const [lookback, setLookback] = useState(existing?.lookback_days ?? 30);
  const [enabled, setEnabled] = useState(existing?.enabled ?? true);
  const [mode, setMode] = useState<Mode>(existing && !existing.sandbox ? "live" : "sandbox");
  const [sandboxToken, setSandboxToken] = useState<string | null>(null);
  const [busy, setBusy] = useState<"verify" | "save" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [verify, setVerify] = useState<VerifyState>({ phase: "idle", result: null });
  const authState = useRef<string | null>(null);
  const popupWatch = useRef<number | null>(null);

  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    container.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  // The sandbox authorization window reports back with postMessage.
  useEffect(() => {
    function onMessage(event: MessageEvent<SandboxAuthMessage>) {
      const data = event.data;
      if (event.origin !== window.location.origin || data?.source !== "cloudpulse-sandbox-auth") return;
      if (!authState.current || data.state !== authState.current || data.kind !== entry.kind) return;
      authState.current = null;
      if (popupWatch.current !== null) window.clearInterval(popupWatch.current);
      setBusy(null);
      if (data.status === "authorized") {
        setSandboxToken(data.token);
        setVerify({ phase: "done", result: sandboxResult(data.identity) });
      } else {
        setVerify({ phase: "idle", result: null });
        setError("Authorization was cancelled.");
      }
    }
    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
      if (popupWatch.current !== null) window.clearInterval(popupWatch.current);
    };
  }, [entry.kind]);

  const fields = entry.fields.filter((f) => visible(f, values));
  const settingsFields = fields.filter((f) => f.section === "settings");
  const authFields = fields.filter((f) => f.section === "auth");
  const needsAuthorization = mode === "sandbox" && !sandboxToken && !existing?.sandbox;

  function set(key: string, value: Value) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  function switchMode(next: Mode) {
    if (next === mode) return;
    setMode(next);
    setSandboxToken(null);
    setError(null);
    setAttempt((n) => n + 1);
    setVerify({ phase: "idle", result: null });
  }

  function openSandboxAuthorization() {
    const state = crypto.randomUUID();
    const url = `/connect/authorize?kind=${entry.kind}&state=${state}`;
    const width = 480;
    const height = 780;
    const left = window.screenX + Math.max(0, (window.outerWidth - width) / 2);
    const top = window.screenY + Math.max(0, (window.outerHeight - height) / 2);
    const popup = window.open(url, "cloudpulse-sandbox-auth", `popup,width=${width},height=${height},left=${left},top=${top}`);
    if (!popup) {
      setError("The authorization window was blocked. Allow pop-ups for this site and try again.");
      return;
    }
    authState.current = state;
    setBusy("verify");
    setAttempt((n) => n + 1);
    setVerify({ phase: "verifying", result: null });
    // Closed without answering: stop waiting.
    popupWatch.current = window.setInterval(() => {
      if (!popup.closed || authState.current !== state) return;
      authState.current = null;
      if (popupWatch.current !== null) window.clearInterval(popupWatch.current);
      setBusy(null);
      setVerify({ phase: "idle", result: null });
    }, 500);
  }

  async function runVerify() {
    setError(null);
    if (mode === "sandbox" && !(existing?.sandbox && !sandboxToken)) {
      openSandboxAuthorization();
      return;
    }
    const { config, credentials } = payloadParts(entry, values, mode, sandboxToken);
    setBusy("verify");
    setAttempt((n) => n + 1);
    setVerify({ phase: "verifying", result: null });
    try {
      // Saved connector with untouched credentials: check the stored ones.
      const result =
        existing && Object.keys(credentials).length === 0
          ? await api.post<VerifyResponse>(`/connectors/${existing.id}/test`)
          : await api.post<VerifyResponse>("/connectors/verify", { kind: entry.kind, config, credentials });
      setVerify({ phase: "done", result });
    } catch (err) {
      setVerify({ phase: "idle", result: null });
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (needsAuthorization) {
      setError("Verify credentials first: authorize the sandbox account in the window that opens.");
      return;
    }
    const { config, credentials } = payloadParts(entry, values, mode, sandboxToken);
    const settings: ConnectorSettingsInput = {
      name,
      enabled,
      config,
      sync_interval_hours: interval,
      lookback_days: lookback,
    };
    setError(null);
    setBusy("save");
    try {
      const saved = existing
        ? await api.put<Connector>(`/connectors/${existing.id}`, {
            ...settings,
            credentials: Object.keys(credentials).length ? credentials : null,
          })
        : await api.post<Connector>("/connectors", { ...settings, kind: entry.kind, credentials });
      onSaved(saved, !existing);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  function renderField(field: CatalogField) {
    const id = `cf-${field.key}`;
    const value = values[field.key];
    if (field.type === "toggle") {
      return (
        <label key={field.key} className="flex items-center gap-2 text-sm text-slate-700 sm:col-span-2">
          <input
            type="checkbox"
            className="size-4 accent-brand-600"
            checked={Boolean(value)}
            onChange={(e) => set(field.key, e.target.checked)}
          />
          {field.label}
        </label>
      );
    }
    // Stored credentials can be kept when editing a connector that already uses real keys.
    const keepStored = Boolean(existing && !existing.sandbox && field.secret);
    const keepHint = keepStored ? `Leave blank to keep the stored value (${existing?.credentials_hint}).` : "";
    return (
      <Field
        key={field.key}
        label={field.required && !keepStored ? `${field.label} *` : field.label}
        htmlFor={id}
        hint={[field.help, keepHint].filter(Boolean).join(" ") || undefined}
      >
        {field.type === "select" ? (
          <select id={id} className={inputClass} value={String(value)} onChange={(e) => set(field.key, e.target.value)}>
            {field.options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        ) : (
          <input
            id={id}
            className={inputClass}
            type={field.type === "secret" ? "password" : field.type === "number" ? "number" : "text"}
            inputMode={field.type === "number" ? "numeric" : undefined}
            autoComplete={field.secret ? "off" : undefined}
            spellCheck={false}
            required={field.required && !keepStored}
            placeholder={field.placeholder || undefined}
            value={typeof value === "boolean" ? "" : value}
            onChange={(e) => set(field.key, e.target.value)}
          />
        )}
      </Field>
    );
  }

  const modeButton = (value: Mode, label: string, Icon: typeof KeyRoundIcon) => (
    <button
      type="button"
      role="radio"
      aria-checked={mode === value}
      onClick={() => switchMode(value)}
      disabled={busy !== null}
      className={cx(
        "inline-flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
        mode === value ? "bg-white text-slate-900 shadow-sm ring-1 ring-slate-200" : "text-slate-600 hover:text-slate-900",
      )}
    >
      <Icon className="size-3.5" aria-hidden />
      {label}
    </button>
  );

  return (
    <div ref={container} className="scroll-mt-20">
      <Card
        title={
          <span className="flex items-center gap-2">
            <ProviderMark provider={entry.provider} className="size-4.5 text-slate-700" />
            {existing ? `Edit ${existing.name}` : `Connect ${entry.name}`}
          </span>
        }
        description={mode === "sandbox" ? "Sandbox: a simulated account, authorized in a mock consent window" : entry.auth}
        action={
          <a
            href={entry.docs_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs font-medium text-brand-700 hover:underline"
          >
            Provider docs <ExternalLinkIcon className="size-3" aria-hidden />
          </a>
        }
        className="animate-appear motion-reduce:animate-none"
      >
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.9fr)]">
          <form onSubmit={submit} className="space-y-5">
            <fieldset className="rounded-lg border border-slate-200 bg-slate-50 p-4">
              <legend className="flex items-center gap-1.5 px-1 text-xs font-semibold text-slate-700">
                <ShieldCheckIcon className="size-3.5 text-good-text" aria-hidden />
                1. Account access
              </legend>
              <div role="radiogroup" aria-label="Account" className="mb-4 flex gap-1 rounded-lg bg-slate-200/60 p-1">
                {modeButton("sandbox", "Sandbox account", FlaskConicalIcon)}
                {modeButton("live", "Your own credentials", KeyRoundIcon)}
              </div>
              {mode === "sandbox" ? (
                <div className="space-y-2 text-sm text-slate-600">
                  <p>
                    Try the whole flow without a {entry.provider === "aws" ? "AWS" : "provider"} account.{" "}
                    <span className="font-medium text-slate-900">Verify credentials</span> opens an authorization window;
                    approve it, close it, then finish the settings below.
                  </p>
                  <p className="text-xs text-slate-500">
                    Sandbox syncs read a simulated API and validate its data, but never import billing data.
                  </p>
                  {sandboxToken && (
                    <p className="text-xs font-medium text-good-text">✓ Access token accepted. Finish the settings and save.</p>
                  )}
                </div>
              ) : (
                <>
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">{authFields.map(renderField)}</div>
                  <p className="mt-3 text-xs text-slate-500">
                    Encrypted at rest and never shown again. Required permissions: {entry.permissions.join(", ")}.
                    {entry.notes.length > 0 && ` ${entry.notes.join(" ")}`}
                  </p>
                </>
              )}
              <div className="mt-4">
                <Button type="button" variant="secondary" onClick={runVerify} disabled={busy !== null}>
                  {busy === "verify"
                    ? mode === "sandbox"
                      ? "Waiting for authorization…"
                      : "Verifying…"
                    : "Verify credentials"}
                </Button>
              </div>
            </fieldset>

            <fieldset className="space-y-4">
              <legend className="mb-3 text-xs font-semibold text-slate-700">2. Connector settings</legend>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <Field label="Name *" htmlFor="cf-name">
                  <input
                    id="cf-name"
                    required
                    maxLength={120}
                    className={inputClass}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </Field>
                <Field label="Sync schedule" htmlFor="cf-interval">
                  <select
                    id="cf-interval"
                    className={inputClass}
                    value={interval}
                    onChange={(e) => setSyncInterval(Number(e.target.value))}
                  >
                    {INTERVALS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </Field>
                {entry.supports_lookback && (
                  <Field label="Days per sync" htmlFor="cf-lookback" hint="Each sync re-reads and reconciles this window.">
                    <input
                      id="cf-lookback"
                      type="number"
                      min={1}
                      max={365}
                      className={inputClass}
                      value={lookback}
                      onChange={(e) => setLookback(Number(e.target.value))}
                    />
                  </Field>
                )}
                {settingsFields.map(renderField)}
                <label className="flex items-center gap-2 text-sm text-slate-700 sm:col-span-2">
                  <input
                    type="checkbox"
                    className="size-4 accent-brand-600"
                    checked={enabled}
                    onChange={(e) => setEnabled(e.target.checked)}
                  />
                  Enabled (scheduled syncs run)
                </label>
              </div>
            </fieldset>

            {error && <Notice tone="error">{error}</Notice>}
            <div className="flex flex-wrap items-center gap-2">
              <Button type="submit" disabled={busy !== null || needsAuthorization}>
                {busy === "save" ? "Saving…" : existing ? "Save changes" : "Save connector"}
              </Button>
              <Button variant="ghost" onClick={onCancel} disabled={busy === "save"}>
                Cancel
              </Button>
              {needsAuthorization && <span className="text-xs text-slate-500">Verify credentials first.</span>}
            </div>
          </form>

          <div>
            <h3 className="mb-3 text-sm font-semibold text-slate-900">Authorization check</h3>
            <VerifyFlow
              key={attempt}
              provider={entry.provider}
              phase={verify.phase}
              result={verify.result}
              sandbox={mode === "sandbox"}
            />
          </div>
        </div>
      </Card>
    </div>
  );
}
