"use client";

import Link from "next/link";
import { useState } from "react";

import { CostAreaChart, CostColumnChart, RankedBars } from "@/components/charts/charts";
import { LoadSampleButton } from "@/components/features/load-sample-button";
import { useDataStatus } from "@/components/shell/data-status";
import {
  ButtonLink,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  Meter,
  PageHeader,
  SeverityBadge,
  StatTile,
  StatusBadge,
  cx,
} from "@/components/ui/primitives";
import {
  errorMessage,
  qs,
  type Breakdown,
  type BudgetStatus,
  type CostSummary,
  type Forecast,
  type IncidentCounts,
  type IncidentSummary,
  type Page,
  type Timeseries,
} from "@/lib/api";
import {
  addDays,
  formatDate,
  formatDateRange,
  formatMoney,
  formatMonth,
  formatPct,
  formatSignedMoney,
  scopeLabel,
  toNumber,
} from "@/lib/format";
import { useApi } from "@/lib/hooks";

const RANGES = [30, 60, 90] as const;

export function OverviewPage() {
  const { status, loading, error, currency, refresh } = useDataStatus();

  if (error) return <ErrorState message={errorMessage(error)} onRetry={refresh} />;
  if (loading && !status) return <LoadingState rows={6} />;
  if (!status?.has_data || !currency) {
    return (
      <>
        <PageHeader title="Overview" />
        <Card>
          <EmptyState
            title="No billing data yet"
            description="Load the built-in synthetic dataset (90 days with two injected anomalies) or upload your own billing CSV to see cost analytics."
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
  return <Overview currency={currency} />;
}

function Overview({ currency }: { currency: string }) {
  const [range, setRange] = useState<(typeof RANGES)[number]>(30);
  const forecast = useApi<Forecast>(`/costs/forecast${qs({ currency })}`);
  const asOf = forecast.data?.currency === currency ? forecast.data.as_of : null;
  const monthStart = forecast.data?.month_start;

  const mtd = useApi<CostSummary>(
    asOf && monthStart ? `/costs/summary${qs({ currency, start: monthStart, end: asOf })}` : null,
  );
  const daily = useApi<Timeseries>(
    asOf
      ? `/costs/timeseries${qs({ currency, granularity: "day", start: addDays(asOf, -(range - 1)), end: asOf })}`
      : null,
  );
  const monthly = useApi<Timeseries>(
    asOf
      ? `/costs/timeseries${qs({ currency, granularity: "month", start: `${addDays(asOf, -334).slice(0, 7)}-01`, end: asOf })}`
      : null,
  );
  const services = useApi<Breakdown>(
    asOf
      ? `/costs/breakdown${qs({ currency, dimension: "service", start: addDays(asOf, -29), end: asOf, limit: 6 })}`
      : null,
  );
  const counts = useApi<IncidentCounts>("/incidents/counts");
  const incidents = useApi<Page<IncidentSummary>>("/incidents?limit=5");
  const budgets = useApi<BudgetStatus[]>("/budgets");

  if (forecast.error) return <ErrorState message={errorMessage(forecast.error)} onRetry={forecast.reload} />;

  const summary = mtd.data;
  const changePct = summary?.change_pct ?? null;
  const unresolved = counts.data ? counts.data.open + counts.data.acknowledged : null;
  const budgetList = budgets.data?.filter((b) => b.budget.currency === currency) ?? [];
  const overBudget = budgetList.filter((b) => b.state === "over_budget").length;

  return (
    <>
      <PageHeader
        title="Overview"
        description={
          asOf ? `Spend in ${currency} through ${formatDate(asOf)} (latest day with billing data).` : undefined
        }
        actions={
          <ButtonLink href="/dashboard/costs" variant="secondary">
            Open cost explorer
          </ButtonLink>
        }
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label="Spend, month to date"
          value={summary ? formatMoney(summary.current.total_cost, currency) : "…"}
          delta={
            summary && changePct !== null
              ? {
                  text: `${formatPct(changePct, true)} vs previous ${summary.current.days_in_period} days`,
                  direction: changePct > 0 ? "up" : changePct < 0 ? "down" : "flat",
                  goodWhen: "down",
                }
              : null
          }
          hint={summary && changePct === null ? "No comparable previous period" : undefined}
        />
        <StatTile
          label="Forecast, month end"
          value={
            forecast.data?.forecast_total ? formatMoney(forecast.data.forecast_total, currency) : forecast.data ? "Not enough data" : "…"
          }
          hint={
            forecast.data?.status === "ok"
              ? `${forecast.data.days_remaining} days left · median ${formatMoney(forecast.data.trailing_daily_median, currency)}/day`
              : forecast.data?.status === "complete"
                ? "Month complete"
                : forecast.data?.message
          }
        />
        <StatTile
          label="Unresolved incidents"
          value={unresolved ?? "…"}
          hint={
            counts.data ? (
              <Link href="/dashboard/incidents" className="font-medium text-brand-700 hover:underline">
                {counts.data.open} open · {counts.data.acknowledged} acknowledged
              </Link>
            ) : undefined
          }
        />
        <StatTile
          label="Budgets"
          value={budgets.data ? `${budgetList.length} tracked` : "…"}
          hint={
            budgets.data ? (
              <Link href="/dashboard/budgets" className={cx("font-medium hover:underline", overBudget ? "text-red-700" : "text-brand-700")}>
                {overBudget ? `${overBudget} over budget` : budgetList.length ? "None over budget" : "Create a budget"}
              </Link>
            ) : undefined
          }
        />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card
          className="xl:col-span-2"
          title="Daily spend"
          description={daily.data ? formatDateRange(daily.data.start, daily.data.end) : undefined}
          action={
            <div role="group" aria-label="Date range" className="inline-flex rounded-lg border border-slate-200 p-0.5">
              {RANGES.map((r) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => setRange(r)}
                  aria-pressed={range === r}
                  className={cx(
                    "rounded-md px-2.5 py-1 text-xs font-medium",
                    range === r ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100",
                  )}
                >
                  {r}d
                </button>
              ))}
            </div>
          }
        >
          {daily.error ? (
            <ErrorState message={errorMessage(daily.error)} onRetry={daily.reload} />
          ) : !daily.data ? (
            <LoadingState rows={5} />
          ) : (
            <div className={cx(daily.loading && "opacity-60")}>
              <CostAreaChart
                currency={currency}
                data={daily.data.points.map((p) => ({
                  label: formatDate(p.period_start, "short"),
                  title: formatDate(p.period_start),
                  value: toNumber(p.cost),
                }))}
              />
              {summary && summary.missing_days.length > 0 && (
                <p className="mt-2 text-xs text-slate-500">
                  {summary.missing_days.length} day(s) this month have no billing data and appear as gaps.
                </p>
              )}
            </div>
          )}
        </Card>

        <Card
          title="Top services"
          description="Last 30 days · share · change vs previous 30 days"
          action={
            <Link href="/dashboard/costs" className="text-xs font-medium text-brand-700 hover:underline">
              View all
            </Link>
          }
        >
          {services.error ? (
            <ErrorState message={errorMessage(services.error)} onRetry={services.reload} />
          ) : !services.data ? (
            <LoadingState rows={6} />
          ) : (
            <RankedBars
              currency={currency}
              rows={services.data.items.map((item) => ({
                key: item.label,
                label: item.label,
                value: Number(item.cost),
                share: item.share_pct,
                change: toNumber(item.change_abs),
                changePct: item.change_pct,
                href: `/dashboard/costs${qs({ service: item.key ?? "(unassigned)" })}`,
              }))}
            />
          )}
        </Card>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card
          className="xl:col-span-2"
          title="Recent incidents"
          action={
            <Link href="/dashboard/incidents" className="text-xs font-medium text-brand-700 hover:underline">
              All incidents
            </Link>
          }
          bodyClassName="p-0"
        >
          {incidents.error ? (
            <div className="p-5">
              <ErrorState message={errorMessage(incidents.error)} onRetry={incidents.reload} />
            </div>
          ) : !incidents.data ? (
            <div className="p-5">
              <LoadingState />
            </div>
          ) : incidents.data.items.length === 0 ? (
            <EmptyState
              title="No incidents"
              description="Detection runs after every import and on a schedule. Nothing unusual has been found."
            />
          ) : (
            <ul className="divide-y divide-slate-100">
              {incidents.data.items.map((incident) => (
                <li key={incident.id}>
                  <Link
                    href={`/dashboard/incidents/${incident.id}`}
                    className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3 hover:bg-slate-50"
                  >
                    <SeverityBadge severity={incident.severity} />
                    <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-900">
                      {scopeLabel(incident.scope_type, incident.scope_value)}
                    </span>
                    <span className="text-xs text-slate-500">
                      {formatDateRange(incident.start_date, incident.end_date)}
                    </span>
                    <span className="tabular text-sm font-medium text-red-700">
                      {formatSignedMoney(incident.deviation_abs, incident.currency)}
                    </span>
                    <StatusBadge status={incident.status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card
          title="Budget utilization"
          action={
            <Link href="/dashboard/budgets" className="text-xs font-medium text-brand-700 hover:underline">
              Manage
            </Link>
          }
        >
          {budgets.error ? (
            <ErrorState message={errorMessage(budgets.error)} onRetry={budgets.reload} />
          ) : !budgets.data ? (
            <LoadingState />
          ) : budgetList.length === 0 ? (
            <EmptyState
              title="No budgets"
              description={`Set a ${currency} budget to track utilization and receive threshold alerts.`}
              action={<ButtonLink href="/dashboard/budgets" size="sm">Create a budget</ButtonLink>}
            />
          ) : (
            <ul className="space-y-4">
              {budgetList.slice(0, 4).map((b) => {
                const pct = toNumber(b.utilization_pct);
                return (
                  <li key={b.budget.id}>
                    <div className="mb-1.5 flex justify-between gap-2 text-sm">
                      <span className="truncate font-medium text-slate-800">{b.budget.name}</span>
                      <span className="tabular shrink-0 text-slate-600">
                        {formatMoney(b.actual, currency)} / {formatMoney(b.budget.amount, currency)}
                      </span>
                    </div>
                    <Meter value={pct} label={`${b.budget.name} utilization`} />
                    <p className="mt-1 text-xs text-slate-500">
                      {pct === null ? "No data" : `${formatPct(pct)} used`} · {b.message}
                    </p>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>

      <div className="mt-4">
        <Card title="Monthly spend" description="Last 12 months · partial months are labelled in the tooltip">
          {monthly.error ? (
            <ErrorState message={errorMessage(monthly.error)} onRetry={monthly.reload} />
          ) : !monthly.data ? (
            <LoadingState rows={5} />
          ) : (
            <CostColumnChart
              currency={currency}
              height={220}
              data={monthly.data.points
                .filter((p) => p.days_with_data > 0)
                .map((p) => ({
                  label: formatMonth(p.period_start),
                  title: formatMonth(p.period_start) + (p.is_partial ? " (partial)" : ""),
                  value: toNumber(p.cost),
                  note: `${p.days_with_data} of ${p.days_in_period} days have data`,
                }))}
            />
          )}
        </Card>
      </div>
    </>
  );
}
