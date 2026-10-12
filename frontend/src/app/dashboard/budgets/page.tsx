"use client";

import { useState, type FormEvent } from "react";

import { useDataStatus } from "@/components/shell/data-status";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  Meter,
  Notice,
  PageHeader,
  Pagination,
  cx,
  inputClass,
} from "@/components/ui/primitives";
import {
  api,
  errorMessage,
  qs,
  type Breakdown,
  type BudgetAlert,
  type BudgetInput,
  type BudgetStatus,
  type Page,
  type ScopeType,
} from "@/lib/api";
import {
  DIMENSION_LABELS,
  addDays,
  formatDate,
  formatDateRange,
  formatDateTime,
  formatMoney,
  formatPct,
  scopeLabel,
  toNumber,
} from "@/lib/format";
import { useApi } from "@/lib/hooks";

const SCOPES: ScopeType[] = ["total", "service", "project", "environment", "provider", "region", "account_id"];
const STATE_BADGE = {
  ok: { tone: "good", label: "Within budget" },
  warning: { tone: "warning", label: "At risk" },
  over_budget: { tone: "critical", label: "Over budget" },
  no_data: { tone: "neutral", label: "No data" },
} as const;

export default function BudgetsPage() {
  const budgets = useApi<BudgetStatus[]>("/budgets");
  const [alertsOffset, setAlertsOffset] = useState(0);
  const alerts = useApi<Page<BudgetAlert>>(`/budgets/alerts${qs({ limit: 10, offset: alertsOffset })}`);
  const [editing, setEditing] = useState<BudgetStatus | "new" | null>(null);
  const [checking, setChecking] = useState(false);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  function reloadAll() {
    budgets.reload();
    alerts.reload();
  }

  async function checkNow() {
    setChecking(true);
    setNotice(null);
    try {
      const result = await api.post<{ notifications_sent: number }>("/budgets/evaluate");
      setNotice({
        tone: "success",
        text:
          result.notifications_sent > 0
            ? `Budgets checked: ${result.notifications_sent} alert notification(s) sent to enabled channels.`
            : "Budgets checked: no new threshold crossings to alert on.",
      });
      reloadAll();
    } catch (err) {
      setNotice({ tone: "error", text: errorMessage(err) });
    } finally {
      setChecking(false);
    }
  }

  async function remove(status: BudgetStatus) {
    if (!window.confirm(`Delete the budget "${status.budget.name}" and its alert history?`)) return;
    try {
      await api.delete(`/budgets/${status.budget.id}`);
      setNotice({ tone: "success", text: `Deleted "${status.budget.name}".` });
      reloadAll();
    } catch (err) {
      setNotice({ tone: "error", text: errorMessage(err) });
    }
  }

  return (
    <>
      <PageHeader
        title="Budgets"
        description="Track spend against monthly, quarterly or yearly budgets. Each threshold alerts once per budget period."
        actions={
          <>
            <Button variant="secondary" onClick={checkNow} disabled={checking}>
              {checking ? "Checking…" : "Check budgets now"}
            </Button>
            <Button onClick={() => setEditing("new")}>New budget</Button>
          </>
        }
      />
      {notice && (
        <div className="mb-4">
          <Notice tone={notice.tone}>{notice.text}</Notice>
        </div>
      )}

      {editing && (
        <div className="mb-4">
          <BudgetForm
            key={editing === "new" ? "new" : editing.budget.id}
            existing={editing === "new" ? null : editing}
            onCancel={() => setEditing(null)}
            onSaved={(name) => {
              setEditing(null);
              setNotice({ tone: "success", text: `Saved "${name}". Use "Check budgets now" to send any due alerts.` });
              reloadAll();
            }}
          />
        </div>
      )}

      {budgets.error ? (
        <ErrorState message={errorMessage(budgets.error)} onRetry={budgets.reload} />
      ) : !budgets.data ? (
        <LoadingState rows={6} />
      ) : budgets.data.length === 0 ? (
        <Card>
          <EmptyState
            title="No budgets yet"
            description="Create a budget to see utilization, a projection to period end, and threshold alerts."
            action={<Button onClick={() => setEditing("new")}>New budget</Button>}
          />
        </Card>
      ) : (
        <div className={cx("grid grid-cols-1 gap-4 lg:grid-cols-2", budgets.loading && "opacity-60")}>
          {budgets.data.map((status) => (
            <BudgetCard key={status.budget.id} status={status} onEdit={() => setEditing(status)} onDelete={() => remove(status)} />
          ))}
        </div>
      )}

      <Card className="mt-4" title="Threshold alerts" description="Recorded crossings and their notifications" bodyClassName="p-0">
        {alerts.error ? (
          <div className="p-5">
            <ErrorState message={errorMessage(alerts.error)} onRetry={alerts.reload} />
          </div>
        ) : !alerts.data ? (
          <div className="p-5">
            <LoadingState />
          </div>
        ) : alerts.data.items.length === 0 ? (
          <EmptyState title="No thresholds crossed yet" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                  <th scope="col" className="px-5 py-2.5 font-medium">Budget</th>
                  <th scope="col" className="px-3 py-2.5 font-medium">Period</th>
                  <th scope="col" className="px-3 py-2.5 text-right font-medium">Threshold</th>
                  <th scope="col" className="px-3 py-2.5 text-right font-medium">Utilization</th>
                  <th scope="col" className="px-5 py-2.5 font-medium">Notified</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {alerts.data.items.map((alert) => {
                  const budget = budgets.data?.find((b) => b.budget.id === alert.budget_id)?.budget;
                  return (
                    <tr key={alert.id}>
                      <td className="px-5 py-2.5 text-slate-900">{budget?.name ?? `Budget #${alert.budget_id}`}</td>
                      <td className="px-3 py-2.5 text-slate-600">{formatDateRange(alert.period_start, alert.period_end)}</td>
                      <td className="tabular px-3 py-2.5 text-right">{alert.threshold_pct}%</td>
                      <td className="tabular px-3 py-2.5 text-right">{formatPct(alert.utilization_pct)}</td>
                      <td className="px-5 py-2.5 text-slate-600">
                        {alert.last_notified_at
                          ? `${formatDateTime(alert.last_notified_at)} (${alert.notification_count}×)`
                          : "Not yet"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="px-5 pb-4">
              <Pagination total={alerts.data.total} limit={10} offset={alertsOffset} onChange={setAlertsOffset} />
            </div>
          </div>
        )}
      </Card>
    </>
  );
}

function BudgetCard({ status, onEdit, onDelete }: { status: BudgetStatus; onEdit: () => void; onDelete: () => void }) {
  const { budget } = status;
  const pct = toNumber(status.utilization_pct);
  const badge = STATE_BADGE[status.state];
  return (
    <Card
      title={budget.name}
      description={`${scopeLabel(budget.scope_type, budget.scope_value)} · ${budget.period} · ${budget.currency}${budget.enabled ? "" : " · disabled"}`}
      action={<Badge tone={badge.tone}>{badge.label}</Badge>}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-2xl font-semibold tracking-tight text-slate-900">
          {formatMoney(status.actual, budget.currency)}
          <span className="ml-1 text-sm font-normal text-slate-500">of {formatMoney(budget.amount, budget.currency)}</span>
        </p>
        <p className="tabular text-sm font-medium text-slate-700">{pct === null ? "—" : formatPct(pct)}</p>
      </div>
      <div className="mt-3">
        <Meter value={pct} label={`${budget.name} utilization`} />
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <div>
          <dt className="text-xs text-slate-500">Period</dt>
          <dd className="text-slate-800">
            {status.period_start && status.period_end ? formatDateRange(status.period_start, status.period_end) : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Projected at period end</dt>
          <dd className="text-slate-800">
            {status.projected_total ? (
              <>
                {formatMoney(status.projected_total, budget.currency)}{" "}
                <span className="text-xs text-slate-500">({formatPct(status.projected_utilization_pct)})</span>
              </>
            ) : (
              "Not enough data"
            )}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Thresholds</dt>
          <dd className="flex flex-wrap gap-1">
            {budget.thresholds.map((t) => (
              <Badge key={t} tone={status.thresholds_crossed.includes(t) ? "critical" : "neutral"}>
                {t}%{status.thresholds_crossed.includes(t) ? " ✓ crossed" : ""}
              </Badge>
            ))}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Data through</dt>
          <dd className="text-slate-800">{formatDate(status.as_of)}</dd>
        </div>
      </dl>
      <p className="mt-3 text-xs text-slate-500">{status.message}</p>
      <div className="mt-4 flex gap-2">
        <Button variant="secondary" size="sm" onClick={onEdit}>
          Edit
        </Button>
        <Button variant="danger" size="sm" onClick={onDelete}>
          Delete
        </Button>
      </div>
    </Card>
  );
}

function BudgetForm({
  existing,
  onCancel,
  onSaved,
}: {
  existing: BudgetStatus | null;
  onCancel: () => void;
  onSaved: (name: string) => void;
}) {
  const { status: dataStatus, currency: activeCurrency } = useDataStatus();
  const initial = existing?.budget;
  const [name, setName] = useState(initial?.name ?? "");
  const [amount, setAmount] = useState(initial ? String(toNumber(initial.amount) ?? "") : "");
  const [currency, setCurrency] = useState(initial?.currency ?? activeCurrency ?? "USD");
  const [period, setPeriod] = useState(initial?.period ?? "monthly");
  const [scopeType, setScopeType] = useState<ScopeType>(initial?.scope_type ?? "total");
  const [scopeValue, setScopeValue] = useState(initial?.scope_value ?? "");
  const [thresholds, setThresholds] = useState((initial?.thresholds ?? [50, 80, 100]).join(", "));
  const [renotify, setRenotify] = useState(initial?.renotify_hours ? String(initial.renotify_hours) : "");
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const end = dataStatus?.data_end;
  const suggestions = useApi<Breakdown>(
    scopeType !== "total" && end
      ? `/costs/breakdown${qs({ currency, dimension: scopeType, start: addDays(end, -89), end, limit: 100 })}`
      : null,
  );

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const parsed = thresholds
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean)
      .map(Number);
    if (!parsed.length || parsed.some((t) => !Number.isInteger(t))) {
      setError("Thresholds must be whole percentages separated by commas, e.g. 50, 80, 100.");
      return;
    }
    const payload: BudgetInput = {
      name,
      amount,
      currency,
      period,
      scope_type: scopeType,
      scope_value: scopeType === "total" ? "" : scopeValue,
      thresholds: parsed,
      renotify_hours: renotify ? Number(renotify) : null,
      enabled,
    };
    setBusy(true);
    try {
      if (existing) await api.put(`/budgets/${existing.budget.id}`, payload);
      else await api.post("/budgets", payload);
      onSaved(name.trim());
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title={existing ? `Edit “${existing.budget.name}”` : "New budget"}>
      <form onSubmit={submit} className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Name" htmlFor="b-name" className="sm:col-span-2">
          <input id="b-name" required maxLength={120} className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Amount" htmlFor="b-amount">
          <input
            id="b-amount"
            required
            type="number"
            min="0.01"
            step="0.01"
            inputMode="decimal"
            className={inputClass}
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </Field>
        <Field label="Currency" htmlFor="b-currency">
          <input
            id="b-currency"
            required
            pattern="[A-Za-z]{3}"
            maxLength={3}
            list="b-currency-list"
            className={inputClass}
            value={currency}
            onChange={(e) => setCurrency(e.target.value.toUpperCase())}
          />
          <datalist id="b-currency-list">
            {dataStatus?.currencies.map((c) => <option key={c} value={c} />)}
          </datalist>
        </Field>
        <Field label="Period" htmlFor="b-period">
          <select id="b-period" className={inputClass} value={period} onChange={(e) => setPeriod(e.target.value as BudgetInput["period"])}>
            <option value="monthly">Monthly</option>
            <option value="quarterly">Quarterly</option>
            <option value="yearly">Yearly</option>
          </select>
        </Field>
        <Field label="Applies to" htmlFor="b-scope">
          <select id="b-scope" className={inputClass} value={scopeType} onChange={(e) => setScopeType(e.target.value as ScopeType)}>
            {SCOPES.map((s) => (
              <option key={s} value={s}>
                {s === "total" ? "All spend" : DIMENSION_LABELS[s]}
              </option>
            ))}
          </select>
        </Field>
        {scopeType !== "total" && (
          <Field label={`${DIMENSION_LABELS[scopeType]} value`} htmlFor="b-scope-value" className="sm:col-span-2">
            <input
              id="b-scope-value"
              required
              maxLength={512}
              list="b-scope-values"
              className={inputClass}
              value={scopeValue}
              onChange={(e) => setScopeValue(e.target.value)}
              placeholder="Exact value as it appears in billing data"
            />
            <datalist id="b-scope-values">
              {suggestions.data?.items.map((i) => <option key={i.label} value={i.key ?? "(unassigned)"} />)}
            </datalist>
          </Field>
        )}
        <Field label="Alert thresholds (%)" htmlFor="b-thresholds" hint="Comma-separated, e.g. 50, 80, 100">
          <input id="b-thresholds" required className={inputClass} value={thresholds} onChange={(e) => setThresholds(e.target.value)} />
        </Field>
        <Field label="Repeat alerts every (hours)" htmlFor="b-renotify" hint="Leave empty to alert once per threshold per period">
          <input
            id="b-renotify"
            type="number"
            min="1"
            max="744"
            className={inputClass}
            value={renotify}
            onChange={(e) => setRenotify(e.target.value)}
          />
        </Field>
        <div className="flex items-center gap-2 sm:col-span-2 lg:col-span-4">
          <input id="b-enabled" type="checkbox" className="size-4 accent-brand-600" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          <label htmlFor="b-enabled" className="text-sm text-slate-700">
            Enabled (evaluated for alerts)
          </label>
        </div>
        {error && (
          <div className="sm:col-span-2 lg:col-span-4">
            <Notice tone="error">{error}</Notice>
          </div>
        )}
        <div className="flex gap-2 sm:col-span-2 lg:col-span-4">
          <Button type="submit" disabled={busy}>
            {busy ? "Saving…" : existing ? "Save changes" : "Create budget"}
          </Button>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </form>
    </Card>
  );
}
