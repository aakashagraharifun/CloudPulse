"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { IncidentChart } from "@/components/charts/charts";
import { useAuth } from "@/components/shell/auth";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  Mono,
  Notice,
  SeverityBadge,
  StatTile,
  StatusBadge,
  cx,
  inputClass,
} from "@/components/ui/primitives";
import {
  ApiError,
  api,
  errorMessage,
  type Contributor,
  type IncidentDetail,
  type Investigation,
} from "@/lib/api";
import {
  formatDate,
  formatDateRange,
  formatDateTime,
  formatMoney,
  formatNumber,
  formatPct,
  formatSignedMoney,
  scopeLabel,
  toNumber,
} from "@/lib/format";
import { useApi } from "@/lib/hooks";

const DRIVER_LABEL: Record<string, string> = {
  usage: "Usage-driven",
  rate: "Rate / price change",
  mixed: "Usage and rate",
  mixed_units: "Several units",
  new: "New",
  unknown: "Usage not available",
};

export function IncidentView() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const valid = Number.isInteger(id) && id > 0;
  const incident = useApi<IncidentDetail>(valid ? `/incidents/${id}` : null);
  const investigation = useApi<Investigation>(valid ? `/incidents/${id}/investigation` : null);

  if (!valid || (incident.error instanceof ApiError && incident.error.status === 404)) {
    return (
      <Card>
        <EmptyState
          title="Incident not found"
          description="It may have been removed, or the link is incorrect."
          action={<Link href="/dashboard/incidents" className="text-sm font-medium text-brand-700 hover:underline">Back to incidents</Link>}
        />
      </Card>
    );
  }
  if (incident.error) return <ErrorState message={errorMessage(incident.error)} onRetry={incident.reload} />;
  if (!incident.data) return <LoadingState rows={10} />;

  const data = incident.data;
  const currency = data.currency;

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-3 text-sm">
        <Link href="/dashboard/incidents" className="text-brand-700 hover:underline">
          Incidents
        </Link>
        <span className="mx-2 text-slate-400">/</span>
        <span className="text-slate-600">#{data.id}</span>
      </nav>

      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <SeverityBadge severity={data.severity} />
            <StatusBadge status={data.status} />
            <Badge>{data.kind === "new_spend" ? "New spend" : "Cost spike"}</Badge>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            {scopeLabel(data.scope_type, data.scope_value)}
          </h1>
          <p className="mt-1 text-sm text-slate-600">
            {formatDateRange(data.start_date, data.end_date)} · {data.detection_count} anomalous day(s) ·{" "}
            {currency}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label="Actual cost" value={formatMoney(data.observed_cost, currency)} hint="Sum over anomalous days" />
        <StatTile label="Expected baseline" value={formatMoney(data.expected_cost, currency)} hint="Sum of daily baselines" />
        <StatTile
          label="Above expected"
          value={<span className="text-red-700">{formatSignedMoney(data.deviation_abs, currency)}</span>}
        />
        <StatTile
          label="Peak day increase"
          value={data.peak_deviation_pct ? formatPct(data.peak_deviation_pct, true) : "n/a"}
          hint={data.peak_deviation_pct ? undefined : "No baseline spend, so a percentage is undefined"}
        />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="min-w-0 space-y-4 xl:col-span-2">
          <Card
            title="Actual vs expected"
            description={
              investigation.data
                ? `Baseline period ${formatDateRange(investigation.data.baseline_start, investigation.data.baseline_end)} · incident period shaded`
                : undefined
            }
          >
            {investigation.error ? (
              <ErrorState message={errorMessage(investigation.error)} onRetry={investigation.reload} />
            ) : !investigation.data ? (
              <LoadingState rows={5} />
            ) : (
              <IncidentChart
                currency={currency}
                highlight={{
                  from: formatDate(data.start_date, "short"),
                  to: formatDate(data.end_date, "short"),
                }}
                data={investigation.data.chart.map((p) => {
                  const cost = toNumber(p.cost);
                  return {
                    label: formatDate(p.day, "short"),
                    title: formatDate(p.day),
                    cost,
                    expected: toNumber(p.expected),
                    anomaly: p.is_anomaly ? cost : null,
                  };
                })}
              />
            )}
          </Card>

          {investigation.data && <Findings investigation={investigation.data} />}
          {investigation.data && <Contributors investigation={investigation.data} />}
          <DetectionEvidence incident={data} />
        </div>

        <div className="min-w-0 space-y-4">
          <Actions incident={data} onChanged={() => { incident.reload(); }} />
          {investigation.data && investigation.data.suggestions.length > 0 && (
            <Card title="Suggested next steps" description="Each suggestion cites the evidence behind it">
              <ol className="space-y-4">
                {investigation.data.suggestions.map((s, i) => (
                  <li key={s.title} className="flex gap-3">
                    <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-brand-50 text-xs font-semibold text-brand-700">
                      {i + 1}
                    </span>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-slate-900 [overflow-wrap:anywhere]">{s.title}</p>
                      <p className="mt-0.5 text-sm text-slate-600">{s.detail}</p>
                      <p className="mt-1 text-xs text-slate-500">
                        <span className="font-medium">Evidence:</span> {s.evidence}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            </Card>
          )}
          {investigation.data && investigation.data.related_incidents.length > 0 && (
            <Card title="Related incidents" description="Overlapping dates in other scopes">
              <ul className="space-y-2">
                {investigation.data.related_incidents.map((r) => (
                  <li key={r.id} className="flex items-center gap-2 text-sm">
                    <SeverityBadge severity={r.severity} />
                    <Link href={`/dashboard/incidents/${r.id}`} className="min-w-0 truncate text-brand-700 hover:underline">
                      {r.title}
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          <Timeline incident={data} />
        </div>
      </div>
    </>
  );
}

function Findings({ investigation }: { investigation: Investigation }) {
  const tone =
    investigation.confidence === "high" ? "good" : investigation.confidence === "medium" ? "warning" : "neutral";
  return (
    <Card
      title="What the billing data shows"
      action={<Badge tone={tone}>Confidence: {investigation.confidence}</Badge>}
    >
      <div className="space-y-3 text-sm text-slate-700">
        {investigation.summary.map((line) => (
          <p key={line}>{line}</p>
        ))}
        {investigation.explanations.length > 0 && (
          <ul className="list-disc space-y-1.5 pl-5 [overflow-wrap:anywhere]">
            {investigation.explanations.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        )}
        <p className="rounded-lg bg-slate-50 p-3 text-slate-700">{investigation.confidence_statement}</p>
        {investigation.limitations.length > 0 && (
          <Notice tone="warning">
            <p className="font-medium">Limitations</p>
            <ul className="mt-1 list-disc space-y-1 pl-5">
              {investigation.limitations.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </Notice>
        )}
      </div>
    </Card>
  );
}

function Contributors({ investigation }: { investigation: Investigation }) {
  const [active, setActive] = useState(0);
  const dims = investigation.dimensions;
  if (dims.length === 0) return null;
  const dim = dims[Math.min(active, dims.length - 1)];
  const currency = investigation.currency;
  const showUsage = dim.contributors.some((c) => c.usage);
  return (
    <Card
      title="Largest contributors to the increase"
      description={`Change = cost during the incident − baseline daily average × ${investigation.current_days_with_data} day(s)`}
      bodyClassName="p-0"
    >
      <div role="tablist" aria-label="Dimension" className="flex flex-wrap gap-1 border-b border-slate-100 px-5 py-3">
        {dims.map((d, i) => (
          <button
            key={d.dimension}
            type="button"
            role="tab"
            aria-selected={i === active}
            onClick={() => setActive(i)}
            className={cx(
              "rounded-md px-3 py-1.5 text-xs font-medium",
              i === active ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100",
            )}
          >
            {d.label}
          </button>
        ))}
      </div>
      {dim.contributors.length === 0 ? (
        <EmptyState title="No increase at this level" description="No member of this dimension cost more than its baseline." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                <th scope="col" className="px-5 py-2.5 font-medium">{dim.label}</th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">Baseline / day</th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">Incident / day</th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">Change</th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">Share of increase</th>
                {showUsage && <th scope="col" className="px-5 py-2.5 font-medium">Driver</th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {dim.contributors.map((c) => (
                <ContributorRow
                  key={c.label}
                  contributor={c}
                  currency={currency}
                  showUsage={showUsage}
                  mono={["resource_id", "usage_type", "account_id", "model"].includes(dim.dimension)}
                />
              ))}
              {toNumber(dim.other_change) !== 0 && (
                <tr className="text-slate-600">
                  <td className="px-5 py-2.5">All other ({Math.max(0, dim.members_total - dim.contributors.length)})</td>
                  <td colSpan={2} />
                  <td className="tabular px-3 py-2.5 text-right">{formatSignedMoney(dim.other_change, currency)}</td>
                  <td colSpan={showUsage ? 2 : 1} />
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function ContributorRow({
  contributor: c,
  currency,
  showUsage,
  mono,
}: {
  contributor: Contributor;
  currency: string;
  showUsage: boolean;
  mono: boolean;
}) {
  const usage = c.usage;
  return (
    <tr className="align-top">
      <td className="max-w-xs px-5 py-2.5">
        {mono ? (
          <Mono className="block truncate text-slate-900">{c.label}</Mono>
        ) : (
          <span className="block truncate text-slate-900">{c.label}</span>
        )}
        {c.is_new && <Badge tone="brand" className="mt-1">New · no baseline spend</Badge>}
      </td>
      <td className="tabular px-3 py-2.5 text-right text-slate-600">{formatMoney(c.baseline_daily_avg, currency)}</td>
      <td className="tabular px-3 py-2.5 text-right text-slate-900">{formatMoney(c.current_daily_avg, currency)}</td>
      <td className="tabular px-3 py-2.5 text-right font-medium text-red-700">{formatSignedMoney(c.change, currency)}</td>
      <td className="tabular px-3 py-2.5 text-right text-slate-700">{formatPct(c.share_of_increase_pct)}</td>
      {showUsage && (
        <td className="px-5 py-2.5 text-xs text-slate-600">
          {usage ? (
            <>
              <span className="font-medium text-slate-800">{DRIVER_LABEL[usage.driver]}</span>
              {usage.quantity_ratio !== null && (
                <span className="block">
                  Usage {formatNumber(usage.baseline_daily_quantity)} → {formatNumber(usage.current_daily_quantity)}{" "}
                  {usage.unit}/day ({usage.quantity_ratio}×)
                </span>
              )}
            </>
          ) : (
            "—"
          )}
        </td>
      )}
    </tr>
  );
}

function DetectionEvidence({ incident }: { incident: IncidentDetail }) {
  const currency = incident.currency;
  return (
    <Card
      title="Detection evidence"
      description="The measured values and thresholds behind each anomalous day"
      bodyClassName="p-0"
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
              <th scope="col" className="px-5 py-2.5 font-medium">Day</th>
              <th scope="col" className="px-3 py-2.5 text-right font-medium">Actual</th>
              <th scope="col" className="px-3 py-2.5 text-right font-medium">Expected</th>
              <th scope="col" className="px-3 py-2.5 text-right font-medium">Deviation</th>
              <th scope="col" className="px-3 py-2.5 text-right font-medium">Robust z</th>
              <th scope="col" className="px-5 py-2.5 font-medium">Baseline</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {incident.detections.map((d) => (
              <tr key={d.id} className="align-top">
                <td className="whitespace-nowrap px-5 py-3">
                  <span className="font-medium text-slate-900">{formatDate(d.anomaly_date)}</span>
                  <span className="mt-1 block"><SeverityBadge severity={d.severity} /></span>
                </td>
                <td className="tabular px-3 py-3 text-right text-slate-900">{formatMoney(d.observed_cost, currency)}</td>
                <td className="tabular px-3 py-3 text-right text-slate-600">{formatMoney(d.expected_cost, currency)}</td>
                <td className="tabular whitespace-nowrap px-3 py-3 text-right text-red-700">
                  {formatSignedMoney(d.deviation_abs, currency)}
                  <span className="block text-xs">{d.deviation_pct ? formatPct(d.deviation_pct, true) : "new spend"}</span>
                </td>
                <td className="tabular px-3 py-3 text-right text-slate-600">{d.z_score ?? "flat baseline"}</td>
                <td className="px-5 py-3 text-xs text-slate-600">
                  {d.baseline_method === "day_of_week_median" ? "Same-weekday median" : "Rolling median"} of{" "}
                  {d.baseline_points} day(s)
                  <details className="mt-1">
                    <summary className="cursor-pointer text-brand-700">Values and thresholds</summary>
                    <p className="mt-1 text-slate-700">{d.evidence.reason}</p>
                    <ul className="mt-1 space-y-0.5">
                      {d.evidence.baseline_values.map(([day, value]) => (
                        <li key={day} className="tabular">
                          {formatDate(day, "short")}: {formatMoney(value, currency)}
                        </li>
                      ))}
                    </ul>
                    <p className="mt-1">
                      Thresholds: +{d.thresholds.pct_threshold}% and +{formatMoney(d.thresholds.abs_threshold, currency)}, z ≥{" "}
                      {d.thresholds.z_threshold}; new spend ≥ {formatMoney(d.thresholds.new_spend_threshold, currency)}
                    </p>
                    <p className="mt-1 text-slate-500">Last evaluated {formatDateTime(d.last_evaluated_at)}</p>
                  </details>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function Actions({ incident, onChanged }: { incident: IncidentDetail; onChanged: () => void }) {
  const { user, can } = useAuth();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function act(path: string, body: Record<string, string | null>) {
    const submitted = text;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/incidents/${incident.id}/${path}`, body);
      // Clear only what was submitted; keep anything typed while the request ran.
      setText((current) => (current === submitted ? "" : current));
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function addNote(event: FormEvent) {
    event.preventDefault();
    void act("notes", { body: text });
  }

  const needsActor = !can("member");
  return (
    <Card title="Response" description={`Actions are recorded as ${user.name}.`}>
      <div className="space-y-3">
        <Field label="Note or resolution" htmlFor="incident-text">
          <textarea
            id="incident-text"
            rows={3}
            className={cx(inputClass, "h-auto py-2")}
            value={text}
            maxLength={5000}
            onChange={(e) => setText(e.target.value)}
            placeholder="What did you find? A resolution note is required to resolve."
          />
        </Field>
        {error && <Notice tone="error">{error}</Notice>}
        {needsActor && (
          <p className="text-xs text-slate-500">You have view-only access; members and admins can respond.</p>
        )}
        <div className="flex flex-wrap gap-2">
          {incident.status === "open" && (
            <Button disabled={busy || needsActor} onClick={() => act("acknowledge", { note: text.trim() || null })}>
              Acknowledge
            </Button>
          )}
          {incident.status !== "resolved" && (
            <Button
              variant="secondary"
              disabled={busy || needsActor || !text.trim()}
              onClick={() => act("resolve", { resolution_note: text })}
              title={!text.trim() ? "Write a resolution note first" : undefined}
            >
              Resolve
            </Button>
          )}
          {incident.status === "resolved" && (
            <Button variant="secondary" disabled={busy || needsActor} onClick={() => act("reopen", { reason: text.trim() || null })}>
              Reopen
            </Button>
          )}
          <form onSubmit={addNote}>
            <Button type="submit" variant="ghost" disabled={busy || needsActor || !text.trim()}>
              Add note
            </Button>
          </form>
        </div>
        {incident.status === "acknowledged" && incident.acknowledged_by && (
          <p className="text-xs text-slate-500">
            Acknowledged by {incident.acknowledged_by} · {formatDateTime(incident.acknowledged_at)}
          </p>
        )}
        {incident.status === "resolved" && (
          <div className="rounded-lg bg-green-50 p-3 text-sm text-good-text">
            <p className="font-medium">
              Resolved by {incident.resolved_by} · {formatDateTime(incident.resolved_at)}
            </p>
            <p className="mt-1 text-slate-700">{incident.resolution_note}</p>
          </div>
        )}
      </div>
    </Card>
  );
}

function Timeline({ incident }: { incident: IncidentDetail }) {
  return (
    <Card title="Timeline">
      <ol className="space-y-4">
        {[...incident.events].reverse().map((event) => (
          <li key={event.id} className="relative pl-5">
            <span aria-hidden className="absolute left-0 top-1.5 size-2 rounded-full bg-slate-300" />
            <p className="text-xs text-slate-500">
              {formatDateTime(event.created_at)} · {event.actor}
            </p>
            <p className="text-sm font-medium capitalize text-slate-900">{event.event_type.replace("_", " ")}</p>
            <p className="mt-0.5 text-sm text-slate-600 [overflow-wrap:anywhere]">{event.message}</p>
          </li>
        ))}
      </ol>
    </Card>
  );
}
