"use client";

import { ExternalLinkIcon, ShieldCheckIcon } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { ProviderMark } from "@/components/features/connectors/flow-stage";
import { VerifyFlow } from "@/components/features/connectors/verify-flow";
import { Button, Card, Field, Notice, inputClass } from "@/components/ui/primitives";
import {
  api,
  errorMessage,
  type CatalogEntry,
  type CatalogField,
  type Connector,
  type ConnectorSettingsInput,
  type VerifyResponse,
} from "@/lib/api";

type Value = string | number | boolean;

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
function payloadParts(entry: CatalogEntry, values: Record<string, Value>) {
  const config: Record<string, unknown> = {};
  const credentials: Record<string, string> = {};
  for (const field of entry.fields) {
    if (!visible(field, values)) continue;
    const raw = values[field.key];
    if (field.secret) {
      if (typeof raw === "string" && raw.trim()) credentials[field.key] = raw.trim();
      continue;
    }
    if (field.type === "toggle") config[field.key] = Boolean(raw);
    else if (field.type === "number") config[field.key] = raw === "" ? undefined : Number(raw);
    else if (typeof raw === "string" && raw.trim()) config[field.key] = raw.trim();
  }
  return { config, credentials };
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
  const [busy, setBusy] = useState<"verify" | "save" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [verify, setVerify] = useState<{ phase: "idle" | "verifying" | "done"; result: VerifyResponse | null }>({
    phase: "idle",
    result: null,
  });

  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    container.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  const fields = entry.fields.filter((f) => visible(f, values));
  const settingsFields = fields.filter((f) => !f.secret);
  const secretFields = fields.filter((f) => f.secret);

  function set(key: string, value: Value) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  async function runVerify() {
    const { config, credentials } = payloadParts(entry, values);
    setError(null);
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
    const { config, credentials } = payloadParts(entry, values);
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
    const keepHint =
      existing && field.secret ? `Leave blank to keep the stored value (${existing.credentials_hint}).` : "";
    return (
      <Field
        key={field.key}
        label={field.required && !(existing && field.secret) ? `${field.label} *` : field.label}
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
            required={field.required && !(existing && field.secret)}
            placeholder={field.placeholder || undefined}
            value={typeof value === "boolean" ? "" : value}
            onChange={(e) => set(field.key, e.target.value)}
          />
        )}
      </Field>
    );
  }

  return (
    <div ref={container} className="scroll-mt-20">
    <Card
      title={
        <span className="flex items-center gap-2">
          <ProviderMark provider={entry.provider} className="size-4.5 text-slate-700" />
          {existing ? `Edit ${existing.name}` : `Connect ${entry.name}`}
        </span>
      }
      description={entry.auth}
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

          <fieldset className="rounded-lg border border-slate-200 bg-slate-50 p-4">
            <legend className="flex items-center gap-1.5 px-1 text-xs font-semibold text-slate-700">
              <ShieldCheckIcon className="size-3.5 text-good-text" aria-hidden />
              Credentials — encrypted at rest, never shown again
            </legend>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">{secretFields.map(renderField)}</div>
            <p className="mt-3 text-xs text-slate-500">
              Required permissions: {entry.permissions.join(", ")}.
              {entry.notes.length > 0 && ` ${entry.notes.join(" ")}`}
            </p>
          </fieldset>

          {error && <Notice tone="error">{error}</Notice>}
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="secondary" onClick={runVerify} disabled={busy !== null}>
              {busy === "verify" ? "Verifying…" : "Verify credentials"}
            </Button>
            <Button type="submit" disabled={busy !== null}>
              {busy === "save" ? "Saving…" : existing ? "Save changes" : "Save connector"}
            </Button>
            <Button variant="ghost" onClick={onCancel} disabled={busy !== null}>
              Cancel
            </Button>
          </div>
        </form>

        <div>
          <h3 className="mb-3 text-sm font-semibold text-slate-900">Authorization check</h3>
          <VerifyFlow key={attempt} provider={entry.provider} phase={verify.phase} result={verify.result} />
        </div>
      </div>
    </Card>
    </div>
  );
}
