"use client";

import Link from "next/link";
import { useState } from "react";

import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  Notice,
  PageHeader,
  Pagination,
  SeverityBadge,
  StatusBadge,
  cx,
  inputClass,
} from "@/components/ui/primitives";
import {
  api,
  errorMessage,
  qs,
  type DetectionRun,
  type IncidentCounts,
  type IncidentStatus,
  type IncidentSummary,
  type Page,
  type Severity,
} from "@/lib/api";
import {
  formatDateRange,
  formatDateTime,
  formatMoney,
  formatPct,
  formatSignedMoney,
  scopeLabel,
} from "@/lib/format";
import { useApi } from "@/lib/hooks";

const LIMIT = 20;
const TABS: { id: IncidentStatus | "all"; label: string }[] = [
  { id: "open", label: "Open" },
  { id: "acknowledged", label: "Acknowledged" },
  { id: "resolved", label: "Resolved" },
  { id: "all", label: "All" },
];

export default function IncidentsPage() {
  const [status, setStatus] = useState<IncidentStatus | "all">("open");
  const [severity, setSeverity] = useState<Severity | "">("");
  const [offset, setOffset] = useState(0);
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<DetectionRun | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  const incidents = useApi<Page<IncidentSummary>>(
    `/incidents${qs({ status: status === "all" ? null : status, severity, limit: LIMIT, offset })}`,
  );
  const counts = useApi<IncidentCounts>("/incidents/counts");
  const runs = useApi<Page<DetectionRun>>("/anomalies/runs?limit=1");
  const lastRun = runResult ?? runs.data?.items[0] ?? null;

  async function runDetection() {
    setRunning(true);
    setRunError(null);
    try {
      const run = await api.post<DetectionRun>("/anomalies/runs");
      setRunResult(run);
      incidents.reload();
      counts.reload();
    } catch (err) {
      setRunError(errorMessage(err));
    } finally {
      setRunning(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Incidents"
        description="Unusual cost increases found by statistical detection. Consecutive anomalous days for the same scope are grouped into one incident."
        actions={
          <Button onClick={runDetection} disabled={running}>
            {running ? "Running detection…" : "Run detection now"}
          </Button>
        }
      />

      {runError && (
        <div className="mb-4">
          <Notice tone="error">{runError}</Notice>
        </div>
      )}
      {runResult && (
        <div className="mb-4">
          <Notice tone={runResult.status === "completed" ? "success" : "error"}>
            {runResult.status === "completed" ? (
              <>
                Detection evaluated {runResult.points_evaluated} day(s) across {runResult.series_evaluated} series:{" "}
                {runResult.anomalies_detected} anomalous day(s), {runResult.incidents_created} new incident(s).
                {runResult.anomalies_detected > 0 && runResult.incidents_created === 0 &&
                  " Existing incidents were updated instead of duplicated."}
              </>
            ) : (
              <>Detection failed: {runResult.error}</>
            )}
          </Notice>
        </div>
      )}

      <Card bodyClassName="p-0">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-3">
          <div role="tablist" aria-label="Incident status" className="flex flex-wrap gap-1">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={status === tab.id}
                onClick={() => {
                  setStatus(tab.id);
                  setOffset(0);
                }}
                className={cx(
                  "rounded-md px-3 py-1.5 text-sm font-medium",
                  status === tab.id ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100",
                )}
              >
                {tab.label}
                {counts.data && tab.id !== "all" && (
                  <span className="ml-1.5 tabular text-xs opacity-75">{counts.data[tab.id]}</span>
                )}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-2 text-xs text-slate-600">
            Severity
            <select
              value={severity}
              onChange={(e) => {
                setSeverity(e.target.value as Severity | "");
                setOffset(0);
              }}
              className={cx(inputClass, "h-8 w-32")}
            >
              <option value="">All</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </label>
        </div>

        {incidents.error ? (
          <div className="p-5">
            <ErrorState message={errorMessage(incidents.error)} onRetry={incidents.reload} />
          </div>
        ) : !incidents.data ? (
          <div className="p-5">
            <LoadingState rows={6} />
          </div>
        ) : incidents.data.items.length === 0 ? (
          <EmptyState
            title={status === "all" ? "No incidents yet" : `No ${status} incidents`}
            description="Detection runs after every import and every six hours when the worker is running. You can also run it now."
          />
        ) : (
          <div className={cx("overflow-x-auto", incidents.loading && "opacity-60")}>
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                  <th scope="col" className="px-5 py-2.5 font-medium">Severity</th>
                  <th scope="col" className="px-3 py-2.5 font-medium">Scope</th>
                  <th scope="col" className="px-3 py-2.5 font-medium">Dates</th>
                  <th scope="col" className="px-3 py-2.5 text-right font-medium">Actual</th>
                  <th scope="col" className="px-3 py-2.5 text-right font-medium">Expected</th>
                  <th scope="col" className="px-3 py-2.5 text-right font-medium">Increase</th>
                  <th scope="col" className="px-5 py-2.5 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {incidents.data.items.map((incident) => (
                  <tr key={incident.id} className="hover:bg-slate-50">
                    <td className="px-5 py-3">
                      <SeverityBadge severity={incident.severity} />
                    </td>
                    <td className="max-w-xs px-3 py-3">
                      <Link
                        href={`/dashboard/incidents/${incident.id}`}
                        className="block truncate font-medium text-brand-700 hover:underline"
                      >
                        {scopeLabel(incident.scope_type, incident.scope_value)}
                      </Link>
                      <span className="text-xs text-slate-500">
                        {incident.kind === "new_spend" ? "New spend" : "Cost spike"} · #{incident.id}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 text-slate-600">
                      {formatDateRange(incident.start_date, incident.end_date)}
                    </td>
                    <td className="tabular px-3 py-3 text-right text-slate-900">
                      {formatMoney(incident.observed_cost, incident.currency)}
                    </td>
                    <td className="tabular px-3 py-3 text-right text-slate-600">
                      {formatMoney(incident.expected_cost, incident.currency)}
                    </td>
                    <td className="tabular whitespace-nowrap px-3 py-3 text-right font-medium text-red-700">
                      {formatSignedMoney(incident.deviation_abs, incident.currency)}
                      {incident.peak_deviation_pct && (
                        <span className="ml-1 text-xs font-normal">(peak {formatPct(incident.peak_deviation_pct, true)})</span>
                      )}
                    </td>
                    <td className="px-5 py-3">
                      <StatusBadge status={incident.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {incidents.data && (
          <div className="px-5 pb-4">
            <Pagination total={incidents.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </div>
        )}
      </Card>

      {lastRun && (
        <Card className="mt-4" title="Latest detection run" description={`#${lastRun.id} · ${lastRun.trigger.replace("_", " ")} · ${formatDateTime(lastRun.started_at)}`}>
          <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-xs text-slate-500">Window evaluated</dt>
              <dd className="mt-0.5 text-slate-900">
                {lastRun.evaluation_start && lastRun.evaluation_end
                  ? formatDateRange(lastRun.evaluation_start, lastRun.evaluation_end)
                  : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Series · days evaluated</dt>
              <dd className="tabular mt-0.5 text-slate-900">
                {lastRun.series_evaluated} · {lastRun.points_evaluated}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Anomalous days</dt>
              <dd className="tabular mt-0.5 text-slate-900">{lastRun.anomalies_detected}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Not evaluated (insufficient history)</dt>
              <dd className="tabular mt-0.5 text-slate-900">{lastRun.points_insufficient_history}</dd>
            </div>
          </dl>
          {lastRun.notes && lastRun.notes.length > 0 && (
            <ul className="mt-4 list-disc space-y-1 pl-5 text-xs text-slate-600">
              {lastRun.notes.slice(0, 8).map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          )}
          {lastRun.error && <p className="mt-3 text-sm text-red-700">{lastRun.error}</p>}
        </Card>
      )}
    </>
  );
}
