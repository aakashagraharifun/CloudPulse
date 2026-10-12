"use client";

import { useState, type FormEvent } from "react";

import { useAuth } from "@/components/shell/auth";
import {
  Button,
  Card,
  ErrorState,
  Field,
  LoadingState,
  Notice,
  inputClass,
} from "@/components/ui/primitives";
import { api, errorMessage, type DetectionSettings, type ScopeType } from "@/lib/api";
import { DIMENSION_LABELS, formatDateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";

const SCOPE_OPTIONS: ScopeType[] = [
  "total",
  "service",
  "project",
  "environment",
  "region",
  "provider",
  "account_id",
  "usage_type",
  "resource_id",
];

type NumericKey = Exclude<keyof DetectionSettings, "scopes" | "updated_at">;

const GROUPS: { title: string; fields: { key: NumericKey; label: string; hint: string; step?: string }[] }[] = [
  {
    title: "When is a day anomalous? (all must be met)",
    fields: [
      { key: "pct_threshold", label: "Minimum increase (%)", hint: "Above the expected baseline", step: "0.01" },
      { key: "abs_threshold", label: "Minimum increase (amount)", hint: "In the data's currency", step: "0.01" },
      { key: "z_threshold", label: "Minimum robust z-score", hint: "0 disables; skipped for flat baselines", step: "0.01" },
      { key: "new_spend_threshold", label: "New spend threshold (amount)", hint: "When the baseline had no cost", step: "0.01" },
    ],
  },
  {
    title: "History and evaluation window",
    fields: [
      { key: "min_history_days", label: "Minimum history (days)", hint: "Fewer days with data: not evaluated" },
      { key: "baseline_window_days", label: "Baseline window (days)", hint: "History considered for the baseline" },
      { key: "evaluation_window_days", label: "Days evaluated per run", hint: "Most recent days with data" },
    ],
  },
  {
    title: "Severity (both % and amount must be reached)",
    fields: [
      { key: "severity_medium_pct", label: "Medium from (%)", hint: "", step: "0.01" },
      { key: "severity_high_pct", label: "High from (%)", hint: "", step: "0.01" },
      { key: "severity_critical_pct", label: "Critical from (%)", hint: "", step: "0.01" },
      { key: "severity_medium_abs", label: "Medium from (amount)", hint: "", step: "0.01" },
      { key: "severity_high_abs", label: "High from (amount)", hint: "", step: "0.01" },
      { key: "severity_critical_abs", label: "Critical from (amount)", hint: "", step: "0.01" },
    ],
  },
];

export function DetectionSettingsForm() {
  const settings = useApi<DetectionSettings>("/anomalies/settings");
  return (
    <Card
      title="Anomaly detection"
      description="Explainable statistical thresholds. Changes apply to future detection runs."
    >
      {settings.error ? (
        <ErrorState message={errorMessage(settings.error)} onRetry={settings.reload} />
      ) : !settings.data ? (
        <LoadingState rows={6} />
      ) : (
        <SettingsForm key={settings.data.updated_at} initial={settings.data} onSaved={settings.reload} />
      )}
    </Card>
  );
}

function SettingsForm({ initial, onSaved }: { initial: DetectionSettings; onSaved: () => void }) {
  const readOnly = !useAuth().can("admin");
  const [values, setValues] = useState<Record<NumericKey, string>>(() => {
    const entries = GROUPS.flatMap((g) => g.fields).map((f) => [f.key, String(Number(initial[f.key]))]);
    return Object.fromEntries(entries) as Record<NumericKey, string>;
  });
  const [scopes, setScopes] = useState<ScopeType[]>(initial.scopes);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      await api.put("/anomalies/settings", {
        ...values,
        min_history_days: Number(values.min_history_days),
        baseline_window_days: Number(values.baseline_window_days),
        evaluation_window_days: Number(values.evaluation_window_days),
        scopes,
      });
      setMessage({ tone: "success", text: "Detection settings saved." });
      onSaved();
    } catch (err) {
      setMessage({ tone: "error", text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  function toggleScope(scope: ScopeType) {
    setScopes((current) =>
      current.includes(scope) ? current.filter((s) => s !== scope) : [...current, scope],
    );
  }

  return (
    <form onSubmit={submit}>
      <fieldset disabled={readOnly} className="space-y-6">
      {GROUPS.map((group) => (
        <fieldset key={group.title}>
          <legend className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">{group.title}</legend>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {group.fields.map((f) => (
              <Field key={f.key} label={f.label} htmlFor={`ds-${f.key}`} hint={f.hint || undefined}>
                <input
                  id={`ds-${f.key}`}
                  type="number"
                  min="0"
                  step={f.step ?? "1"}
                  required
                  className={inputClass}
                  value={values[f.key]}
                  onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                />
              </Field>
            ))}
          </div>
        </fieldset>
      ))}
      <fieldset>
        <legend className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
          What to evaluate (each value becomes its own daily series)
        </legend>
        <div className="flex flex-wrap gap-x-5 gap-y-2">
          {SCOPE_OPTIONS.map((scope) => (
            <label key={scope} className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                className="size-4 accent-brand-600"
                checked={scopes.includes(scope)}
                onChange={() => toggleScope(scope)}
              />
              {scope === "total" ? "Total spend" : `Each ${DIMENSION_LABELS[scope].toLowerCase()}`}
            </label>
          ))}
        </div>
        {scopes.length === 0 && <p className="mt-2 text-xs text-red-700">Select at least one scope.</p>}
      </fieldset>
      {message && <Notice tone={message.tone}>{message.text}</Notice>}
      <div className="flex flex-wrap items-center gap-3">
        {!readOnly && (
          <Button type="submit" disabled={busy || scopes.length === 0}>
            {busy ? "Saving…" : "Save detection settings"}
          </Button>
        )}
        <span className="text-xs text-slate-500">Last updated {formatDateTime(initial.updated_at)}</span>
      </div>
      </fieldset>
    </form>
  );
}
