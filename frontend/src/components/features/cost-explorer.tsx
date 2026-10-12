"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { CostAreaChart, CostColumnChart } from "@/components/charts/charts";
import { LoadSampleButton } from "@/components/features/load-sample-button";
import { useDataStatus } from "@/components/shell/data-status";
import {
  Badge,
  Button,
  ButtonLink,
  Card,
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  PageHeader,
  StatTile,
  cx,
  inputClass,
} from "@/components/ui/primitives";
import {
  errorMessage,
  qs,
  type Breakdown,
  type CostSummary,
  type Dimension,
  type Granularity,
  type Timeseries,
} from "@/lib/api";
import {
  DIMENSION_LABELS,
  addDays,
  dimensionValueLabel,
  formatDate,
  formatDateRange,
  formatMoney,
  formatMonth,
  formatPct,
  formatSignedMoney,
  startOfMonth,
  toNumber,
} from "@/lib/format";
import { useApi } from "@/lib/hooks";

const FILTER_KEYS: Dimension[] = [
  "category",
  "provider",
  "account_id",
  "service",
  "region",
  "resource_id",
  "usage_type",
  "model",
  "project",
  "environment",
];
const GROUP_BY: Dimension[] = [
  "service",
  "provider",
  "category",
  "model",
  "project",
  "environment",
  "region",
  "resource_id",
  "usage_type",
  "account_id",
];
const PRESETS = [
  { id: "7", label: "7 days", days: 7 },
  { id: "30", label: "30 days", days: 30 },
  { id: "90", label: "90 days", days: 90 },
  { id: "mtd", label: "Month to date", days: null },
] as const;

export function CostExplorer() {
  const { status, loading, error, currency, refresh } = useDataStatus();
  if (error) return <ErrorState message={errorMessage(error)} onRetry={refresh} />;
  if (loading && !status) return <LoadingState rows={8} />;
  if (!status?.has_data || !currency) {
    return (
      <>
        <PageHeader title="Cost explorer" />
        <Card>
          <EmptyState
            title="No billing data to explore"
            description="Import a billing CSV or load the sample dataset first."
            action={
              <>
                <LoadSampleButton />
                <ButtonLink href="/dashboard/imports" variant="secondary">
                  Upload a CSV
                </ButtonLink>
              </>
            }
          />
        </Card>
      </>
    );
  }
  return <Explorer currency={currency} />;
}

function Explorer({ currency }: { currency: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const start = params.get("start");
  const end = params.get("end");
  const granularity = (params.get("granularity") as Granularity | null) ?? "day";
  const groupBy = (params.get("group") as Dimension | null) ?? "service";
  const filters = Object.fromEntries(
    FILTER_KEYS.flatMap((key) => {
      const value = params.get(key);
      return value ? [[key, value]] : [];
    }),
  ) as Partial<Record<Dimension, string>>;

  function update(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params.toString());
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === "") next.delete(key);
      else next.set(key, value);
    }
    const text = next.toString();
    router.replace(text ? `${pathname}?${text}` : pathname, { scroll: false });
  }

  // Without an explicit range the API defaults to the 30 days ending on the
  // latest day with data; the summary tells us which dates that resolved to.
  const summary = useApi<CostSummary>(`/costs/summary${qs({ currency, start, end, ...filters })}`);
  const range =
    summary.data && summary.data.currency === currency
      ? { start: summary.data.current.start, end: summary.data.current.end }
      : null;
  const asOf = summary.data?.as_of ?? null;

  const series = useApi<Timeseries>(
    range ? `/costs/timeseries${qs({ currency, granularity, ...range, ...filters })}` : null,
  );
  const breakdown = useApi<Breakdown>(
    range ? `/costs/breakdown${qs({ currency, dimension: groupBy, limit: 25, ...range, ...filters })}` : null,
  );

  const activePreset = (() => {
    if (!range || !asOf || range.end !== asOf) return null;
    if (range.start === startOfMonth(asOf)) return "mtd";
    const days = (Date.parse(range.end) - Date.parse(range.start)) / 86_400_000 + 1;
    return PRESETS.find((p) => p.days === days)?.id ?? null;
  })();

  function applyPreset(preset: (typeof PRESETS)[number]) {
    if (!asOf) return;
    update({
      start: preset.days === null ? startOfMonth(asOf) : addDays(asOf, -(preset.days - 1)),
      end: asOf,
    });
  }

  const s = summary.data;
  const changePct = s?.change_pct ?? null;
  const filterEntries = Object.entries(filters) as [Dimension, string][];

  return (
    <>
      <PageHeader
        title="Cost explorer"
        description="Slice spend by any billing dimension. Click a row in the breakdown to filter by it."
      />

      {/* Filter bar: one row of controls above everything they affect */}
      <Card bodyClassName="p-4">
        <div className="flex flex-wrap items-end gap-3">
          <div role="group" aria-label="Date range presets" className="inline-flex flex-wrap rounded-lg border border-slate-200 p-0.5">
            {PRESETS.map((preset) => (
              <button
                key={preset.id}
                type="button"
                disabled={!asOf}
                onClick={() => applyPreset(preset)}
                aria-pressed={activePreset === preset.id}
                className={cx(
                  "rounded-md px-2.5 py-1.5 text-xs font-medium",
                  activePreset === preset.id ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100",
                )}
              >
                {preset.label}
              </button>
            ))}
          </div>
          <Field label="From" htmlFor="range-start" className="w-40">
            <input
              id="range-start"
              type="date"
              className={inputClass}
              value={range?.start ?? ""}
              max={range?.end}
              onChange={(e) => e.target.value && update({ start: e.target.value, end: range?.end ?? null })}
            />
          </Field>
          <Field label="To" htmlFor="range-end" className="w-40">
            <input
              id="range-end"
              type="date"
              className={inputClass}
              value={range?.end ?? ""}
              min={range?.start}
              onChange={(e) => e.target.value && update({ end: e.target.value, start: range?.start ?? null })}
            />
          </Field>
          <Field label="Granularity" htmlFor="granularity" className="w-32">
            <select
              id="granularity"
              className={inputClass}
              value={granularity}
              onChange={(e) => update({ granularity: e.target.value === "day" ? null : e.target.value })}
            >
              <option value="day">Daily</option>
              <option value="week">Weekly</option>
              <option value="month">Monthly</option>
            </select>
          </Field>
          <Field label="Group by" htmlFor="group-by" className="w-40">
            <select
              id="group-by"
              className={inputClass}
              value={groupBy}
              onChange={(e) => update({ group: e.target.value === "service" ? null : e.target.value })}
            >
              {GROUP_BY.map((d) => (
                <option key={d} value={d}>
                  {DIMENSION_LABELS[d]}
                </option>
              ))}
            </select>
          </Field>
          {(start || end || filterEntries.length > 0 || granularity !== "day" || groupBy !== "service") && (
            <Button variant="ghost" onClick={() => router.replace(pathname, { scroll: false })}>
              Reset
            </Button>
          )}
        </div>
        {filterEntries.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="text-xs text-slate-500">Filters:</span>
            {filterEntries.map(([key, value]) => (
              <button
                key={key}
                type="button"
                onClick={() => update({ [key]: null })}
                className="inline-flex items-center gap-1.5 rounded-md bg-brand-50 px-2 py-1 text-xs font-medium text-brand-700 ring-1 ring-brand-100 hover:bg-brand-100"
                aria-label={`Remove filter ${DIMENSION_LABELS[key]}: ${value}`}
              >
                {DIMENSION_LABELS[key]}: <span className="max-w-48 truncate">{dimensionValueLabel(key, value)}</span>
                <span aria-hidden>✕</span>
              </button>
            ))}
          </div>
        )}
      </Card>

      {summary.error ? (
        <div className="mt-4">
          <ErrorState message={errorMessage(summary.error)} onRetry={summary.reload} />
        </div>
      ) : (
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatTile
            label="Total spend"
            value={s ? formatMoney(s.current.total_cost, currency) : "…"}
            hint={s ? formatDateRange(s.current.start, s.current.end) : undefined}
          />
          <StatTile
            label="Change vs previous period"
            value={s ? (s.change_abs === null ? "—" : formatSignedMoney(s.change_abs, currency)) : "…"}
            delta={
              s && changePct !== null
                ? {
                    text: formatPct(changePct, true),
                    direction: changePct > 0 ? "up" : changePct < 0 ? "down" : "flat",
                    goodWhen: "down",
                  }
                : null
            }
            hint={s ? (s.change_abs === null ? "No data in the previous period" : `vs ${formatDateRange(s.previous.start, s.previous.end)}`) : undefined}
          />
          <StatTile
            label="Daily average"
            value={s ? formatMoney(s.daily_average, currency) : "…"}
            hint="Across days that have billing data"
          />
          <StatTile
            label="Days with data"
            value={s ? `${s.current.days_with_data} / ${s.current.days_in_period}` : "…"}
            hint={
              s && s.missing_days.length > 0
                ? `${s.missing_days.length} missing day(s) are excluded, not counted as zero`
                : s
                  ? "Complete coverage"
                  : undefined
            }
          />
        </div>
      )}

      <div className="mt-4">
        <Card
          title={`${granularity === "day" ? "Daily" : granularity === "week" ? "Weekly" : "Monthly"} spend`}
          description={
            filterEntries.length
              ? filterEntries.map(([k, v]) => `${DIMENSION_LABELS[k]}: ${dimensionValueLabel(k, v)}`).join(" · ")
              : "All spend"
          }
        >
          {series.error ? (
            <ErrorState message={errorMessage(series.error)} onRetry={series.reload} />
          ) : !series.data ? (
            <LoadingState rows={5} />
          ) : series.data.points.every((p) => p.cost === null) ? (
            <EmptyState title="No billing data in this range" description="Choose a different date range." />
          ) : (
            <div className={cx(series.loading && "opacity-60")}>
              {series.data.granularity === "day" ? (
                <CostAreaChart
                  currency={currency}
                  height={300}
                  data={series.data.points.map((p) => ({
                    label: formatDate(p.period_start, "short"),
                    title: formatDate(p.period_start),
                    value: toNumber(p.cost),
                  }))}
                />
              ) : (
                <CostColumnChart
                  currency={currency}
                  height={300}
                  data={series.data.points.map((p) => ({
                    label:
                      series.data?.granularity === "month"
                        ? formatMonth(p.period_start)
                        : formatDate(p.period_start, "short"),
                    title:
                      (series.data?.granularity === "month"
                        ? formatMonth(p.period_start)
                        : `Week of ${formatDate(p.period_start)}`) + (p.is_partial ? " (partial)" : ""),
                    value: toNumber(p.cost),
                    note: `${p.days_with_data} of ${p.days_in_period} days have data`,
                  }))}
                />
              )}
            </div>
          )}
        </Card>
      </div>

      <div className="mt-4">
        <BreakdownTable
          breakdown={breakdown.data}
          loading={breakdown.loading}
          error={breakdown.error}
          onRetry={breakdown.reload}
          currency={currency}
          groupBy={groupBy}
          filtered={Boolean(filters[groupBy])}
          onSelect={(value) => update({ [groupBy]: value })}
        />
      </div>
    </>
  );
}

function BreakdownTable({
  breakdown,
  loading,
  error,
  onRetry,
  currency,
  groupBy,
  filtered,
  onSelect,
}: {
  breakdown: Breakdown | undefined;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  currency: string;
  groupBy: Dimension;
  filtered: boolean;
  onSelect: (value: string) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const items = breakdown?.items ?? [];
  const visible = showAll ? items : items.slice(0, 10);
  return (
    <Card
      title={`Breakdown by ${DIMENSION_LABELS[groupBy].toLowerCase()}`}
      description={
        breakdown
          ? `Compared with ${formatDateRange(breakdown.previous_start, breakdown.previous_end)}`
          : undefined
      }
      bodyClassName="p-0"
    >
      {error ? (
        <div className="p-5">
          <ErrorState message={errorMessage(error)} onRetry={onRetry} />
        </div>
      ) : !breakdown ? (
        <div className="p-5">
          <LoadingState rows={6} />
        </div>
      ) : items.length === 0 ? (
        <EmptyState title="No costs in this range" />
      ) : (
        <div className={cx("overflow-x-auto", loading && "opacity-60")}>
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                <th scope="col" className="px-5 py-2.5 font-medium">{DIMENSION_LABELS[groupBy]}</th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">Cost</th>
                <th scope="col" className="w-40 px-3 py-2.5 font-medium">Share</th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">Previous</th>
                <th scope="col" className="px-5 py-2.5 text-right font-medium">Change</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {visible.map((item) => {
                const change = toNumber(item.change_abs) ?? 0;
                const label = item.key === null ? item.label : dimensionValueLabel(groupBy, item.key);
                return (
                  <tr key={item.label} className="hover:bg-slate-50">
                    <td className="max-w-xs px-5 py-2.5">
                      {filtered ? (
                        <span className="block truncate text-slate-800" title={label}>{label}</span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => onSelect(item.key ?? "(unassigned)")}
                          className="block max-w-full truncate text-left font-medium text-brand-700 hover:underline"
                          title={`Filter by ${label}`}
                        >
                          {label}
                        </button>
                      )}
                      {item.key === null && (
                        <Badge className="mt-1">
                          {groupBy === "model" ? "Not model usage" : `No ${DIMENSION_LABELS[groupBy].toLowerCase()} tag`}
                        </Badge>
                      )}
                    </td>
                    <td className="tabular px-3 py-2.5 text-right font-medium text-slate-900">
                      {formatMoney(item.cost, currency)}
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                          <div className="h-full rounded-full bg-series-1" style={{ width: `${Math.max(0, item.share_pct ?? 0)}%` }} />
                        </div>
                        <span className="tabular w-12 text-right text-xs text-slate-600">{formatPct(item.share_pct)}</span>
                      </div>
                    </td>
                    <td className="tabular px-3 py-2.5 text-right text-slate-600">{formatMoney(item.previous_cost, currency)}</td>
                    <td className={cx("tabular px-5 py-2.5 text-right", change > 0 ? "text-red-700" : change < 0 ? "text-good-text" : "text-slate-500")}>
                      {formatSignedMoney(item.change_abs, currency)}
                      <span className="ml-1 text-xs">
                        ({item.change_pct === null ? (change > 0 ? "new" : "—") : formatPct(item.change_pct, true)})
                      </span>
                    </td>
                  </tr>
                );
              })}
              {breakdown.other_count > 0 && (
                <tr className="text-slate-600">
                  <td className="px-5 py-2.5">Other ({breakdown.other_count})</td>
                  <td className="tabular px-3 py-2.5 text-right">{formatMoney(breakdown.other_cost, currency)}</td>
                  <td colSpan={3} />
                </tr>
              )}
            </tbody>
            <tfoot>
              <tr className="border-t border-slate-200 font-semibold text-slate-900">
                <td className="px-5 py-2.5">Total</td>
                <td className="tabular px-3 py-2.5 text-right">{formatMoney(breakdown.total_cost, currency)}</td>
                <td colSpan={3} />
              </tr>
            </tfoot>
          </table>
          {items.length > 10 && (
            <div className="border-t border-slate-100 px-5 py-3">
              <Button variant="ghost" size="sm" onClick={() => setShowAll((v) => !v)}>
                {showAll ? "Show top 10" : `Show all ${items.length}`}
              </Button>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
