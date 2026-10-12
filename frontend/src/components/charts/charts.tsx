"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  ReferenceArea,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { cx } from "@/components/ui/primitives";
import { formatMoney, formatPct, formatSignedMoney, toNumber } from "@/lib/format";

// Chart chrome (docs/design.md §3): recessive hairline grid, muted axis text.
const GRID = "#e2e8f0";
const AXIS_TEXT = "#64748b";
const SERIES_1 = "#2a78d6";
const SERIES_2 = "#eb6834";
const CRITICAL = "#d03b3b";
const SURFACE = "#ffffff";

const axisProps = {
  tick: { fill: AXIS_TEXT, fontSize: 12 },
  tickLine: false,
  axisLine: { stroke: "#cbd5e1" },
} as const;

function TooltipBox({ title, rows }: { title: string; rows: [string, ReactNode][] }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg">
      <p className="mb-1 font-semibold text-slate-900">{title}</p>
      {rows.map(([label, value]) => (
        <p key={label} className="flex justify-between gap-4 text-slate-600">
          <span>{label}</span>
          <span className="tabular font-medium text-slate-900">{value}</span>
        </p>
      ))}
    </div>
  );
}

export type SeriesDatum = {
  label: string; // x-axis label
  title: string; // tooltip title
  value: number | null; // null = no billing data
  partial?: boolean;
  note?: string;
};

/** Cost over time as a 2px line with a 10% wash. Gaps mark days without data. */
export function CostAreaChart({
  data,
  currency,
  height = 260,
}: {
  data: SeriesDatum[];
  currency: string;
  height?: number;
}) {
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis dataKey="label" {...axisProps} minTickGap={24} />
          <YAxis
            {...axisProps}
            axisLine={false}
            width={64}
            tickFormatter={(v: number) => formatMoney(v, currency, { compact: true })}
          />
          <Tooltip
            cursor={{ stroke: "#94a3b8", strokeWidth: 1 }}
            content={({ active, payload }) => {
              const datum = payload?.[0]?.payload as SeriesDatum | undefined;
              if (!active || !datum) return null;
              return (
                <TooltipBox
                  title={datum.title}
                  rows={[
                    ["Cost", datum.value === null ? "No billing data" : formatMoney(datum.value, currency)],
                    ...(datum.note ? ([["Note", datum.note]] as [string, string][]) : []),
                  ]}
                />
              );
            }}
          />
          <Area
            type="linear"
            dataKey="value"
            stroke={SERIES_1}
            strokeWidth={2}
            fill={SERIES_1}
            fillOpacity={0.1}
            connectNulls={false}
            isAnimationActive={false}
            activeDot={{ r: 4, stroke: SURFACE, strokeWidth: 2, fill: SERIES_1 }}
            dot={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Discrete periods (weeks, months) as columns: <=24px wide, 4px rounded top. */
export function CostColumnChart({
  data,
  currency,
  height = 260,
}: {
  data: SeriesDatum[];
  currency: string;
  height?: number;
}) {
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis dataKey="label" {...axisProps} minTickGap={8} />
          <YAxis
            {...axisProps}
            axisLine={false}
            width={64}
            tickFormatter={(v: number) => formatMoney(v, currency, { compact: true })}
          />
          <Tooltip
            cursor={{ fill: "#f1f5f9" }}
            content={({ active, payload }) => {
              const datum = payload?.[0]?.payload as SeriesDatum | undefined;
              if (!active || !datum) return null;
              return (
                <TooltipBox
                  title={datum.title}
                  rows={[
                    ["Cost", datum.value === null ? "No billing data" : formatMoney(datum.value, currency)],
                    ...(datum.note ? ([["Coverage", datum.note]] as [string, string][]) : []),
                  ]}
                />
              );
            }}
          />
          <Bar
            dataKey="value"
            fill={SERIES_1}
            maxBarSize={24}
            radius={[4, 4, 0, 0]}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export type IncidentDatum = {
  label: string;
  title: string;
  cost: number | null;
  expected: number | null;
  anomaly: number | null; // cost on anomalous days only (drawn as critical markers)
};

/** Actual daily cost with the expected baseline and anomalous days marked. */
export function IncidentChart({
  data,
  currency,
  highlight,
  height = 280,
}: {
  data: IncidentDatum[];
  currency: string;
  highlight: { from: string; to: string } | null;
  height?: number;
}) {
  return (
    <div>
      <ul className="mb-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-600" aria-label="Legend">
        <li className="flex items-center gap-2">
          <span aria-hidden className="h-0.5 w-4 rounded" style={{ background: SERIES_1 }} />
          Actual daily cost
        </li>
        <li className="flex items-center gap-2">
          <span aria-hidden className="size-2.5 rounded-full" style={{ background: SERIES_2 }} />
          Expected baseline (anomalous days)
        </li>
        <li className="flex items-center gap-2">
          <span aria-hidden className="size-2.5 rounded-full" style={{ background: CRITICAL }} />
          Anomalous day
        </li>
      </ul>
      <div style={{ height }} className="w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke={GRID} />
            {highlight && (
              <ReferenceArea x1={highlight.from} x2={highlight.to} fill="#fee2e2" fillOpacity={0.6} />
            )}
            <XAxis dataKey="label" {...axisProps} minTickGap={24} />
            <YAxis
              {...axisProps}
              axisLine={false}
              width={64}
              tickFormatter={(v: number) => formatMoney(v, currency, { compact: true })}
            />
            <Tooltip
              cursor={{ stroke: "#94a3b8", strokeWidth: 1 }}
              content={({ active, payload }) => {
                const datum = payload?.[0]?.payload as IncidentDatum | undefined;
                if (!active || !datum) return null;
                const rows: [string, ReactNode][] = [
                  ["Actual", datum.cost === null ? "No billing data" : formatMoney(datum.cost, currency)],
                ];
                if (datum.expected !== null) {
                  rows.push(["Expected", formatMoney(datum.expected, currency)]);
                  if (datum.cost !== null)
                    rows.push(["Above expected", formatSignedMoney(datum.cost - datum.expected, currency)]);
                }
                return <TooltipBox title={datum.title + (datum.anomaly !== null ? " · anomalous" : "")} rows={rows} />;
              }}
            />
            <Area
              type="linear"
              dataKey="cost"
              stroke={SERIES_1}
              strokeWidth={2}
              fill={SERIES_1}
              fillOpacity={0.1}
              connectNulls={false}
              isAnimationActive={false}
              dot={false}
              activeDot={{ r: 4, stroke: SURFACE, strokeWidth: 2, fill: SERIES_1 }}
            />
            <Scatter dataKey="expected" fill={SERIES_2} stroke={SURFACE} strokeWidth={2} isAnimationActive={false} />
            <Scatter dataKey="anomaly" fill={CRITICAL} stroke={SURFACE} strokeWidth={2} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export type BarRow = {
  key: string;
  label: string;
  value: number;
  share: number | null;
  change: number | null;
  changePct: number | null;
  href?: string;
  onSelect?: () => void;
};

/**
 * Ranked horizontal bars rendered in HTML: long names stay readable and every
 * value is printed, so the chart doubles as its own table.
 */
export function RankedBars({
  rows,
  currency,
  showChange = true,
  emptyText = "No costs in this period.",
}: {
  rows: BarRow[];
  currency: string;
  showChange?: boolean;
  emptyText?: string;
}) {
  if (!rows.length) return <p className="py-6 text-center text-sm text-slate-500">{emptyText}</p>;
  const max = Math.max(...rows.map((r) => Math.abs(r.value)), 0) || 1;
  return (
    <ul className="space-y-3">
      {rows.map((row) => {
        const content = (
          <>
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="min-w-0 truncate text-slate-800" title={row.label}>
                {row.label}
              </span>
              <span className="tabular shrink-0 font-medium text-slate-900">
                {formatMoney(row.value, currency)}
              </span>
            </div>
            <div className="mt-1.5 flex items-center gap-3">
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                <div
                  className="h-full rounded-full"
                  style={{ width: `${(Math.max(0, row.value) / max) * 100}%`, background: SERIES_1 }}
                />
              </div>
              <span className="tabular w-12 shrink-0 text-right text-xs text-slate-500">
                {row.share === null ? "—" : formatPct(row.share)}
              </span>
              {showChange && (
                <span
                  className={cx(
                    "tabular w-16 shrink-0 text-right text-xs",
                    row.change === null || row.change === 0
                      ? "text-slate-500"
                      : row.change > 0
                        ? "text-red-700"
                        : "text-good-text",
                  )}
                  title="Change vs previous period"
                >
                  {row.changePct === null
                    ? row.change && row.change > 0
                      ? "new"
                      : "—"
                    : formatPct(row.changePct, true)}
                </span>
              )}
            </div>
          </>
        );
        return (
          <li key={row.key}>
            {row.href ? (
              <Link href={row.href} className="block rounded-md p-1 -m-1 hover:bg-slate-50">
                {content}
              </Link>
            ) : row.onSelect ? (
              <button type="button" onClick={row.onSelect} className="block w-full rounded-md p-1 -m-1 text-left hover:bg-slate-50">
                {content}
              </button>
            ) : (
              content
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function toSeriesValue(value: string | null): number | null {
  return toNumber(value);
}
