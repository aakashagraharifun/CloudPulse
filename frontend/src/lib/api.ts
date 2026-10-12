/**
 * Typed client for the CloudPulse API (/api/v1).
 *
 * Monetary amounts arrive as decimal strings (e.g. "1234.5000") so no precision
 * is lost in JSON; they are converted to numbers only for display and charts.
 */
import { API_BASE_URL } from "@/lib/config";

export type Money = string;

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code: string,
    public readonly details: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type ErrorEnvelope = { error?: { code?: string; message?: string; details?: unknown } };

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/v1${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init.body && !(init.body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...init.headers,
      },
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(
      `Cannot reach the CloudPulse API at ${API_BASE_URL}. Is the backend running?`,
      0,
      "network_error",
    );
  }
  if (response.status === 204) return undefined as T;
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const envelope = (body ?? {}) as ErrorEnvelope;
    throw new ApiError(
      envelope.error?.message ?? `Request failed with status ${response.status}`,
      response.status,
      envelope.error?.code ?? "http_error",
      envelope.error?.details ?? null,
    );
  }
  return body as T;
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body),
    }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  delete: (path: string) => request<void>(path, { method: "DELETE" }),
  /** DELETE for endpoints that return a JSON body (e.g. allocation rules). */
  deleteWithBody: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

/** Build a query string, skipping empty values. */
export function qs(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

/** Human-readable message for any thrown value, including validation details. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === "validation_error" && Array.isArray(err.details)) {
      const parts = (err.details as { location?: string; message?: string }[])
        .map((d) => [d.location?.replace(/^body\.?/, ""), d.message].filter(Boolean).join(": "))
        .filter(Boolean);
      if (parts.length) return parts.join(" · ");
    }
    return err.message;
  }
  return err instanceof Error ? err.message : "Something went wrong.";
}

// --- shared ------------------------------------------------------------------

export type Page<T> = { items: T[]; total: number; limit: number; offset: number };
export type Severity = "low" | "medium" | "high" | "critical";
export type IncidentStatus = "open" | "acknowledged" | "resolved";
export type Dimension =
  | "provider"
  | "account_id"
  | "service"
  | "region"
  | "resource_id"
  | "usage_type"
  | "project"
  | "environment";
export type ScopeType = "total" | Dimension;

// --- health ------------------------------------------------------------------

export type Readiness = {
  status: "ready" | "not_ready";
  database: { status: "ok" | "error"; detail: string | null };
  redis: { status: "ok" | "error"; detail: string | null };
};

// --- imports -----------------------------------------------------------------

export type ImportRowError = { line: number | null; column: string | null; message: string };

export type ImportSummary = {
  id: number;
  filename: string;
  source: "upload" | "sample";
  status: "processing" | "completed" | "failed";
  detected_format: string | null;
  file_size_bytes: number;
  rows_total: number;
  rows_inserted: number;
  rows_duplicate: number;
  rows_invalid: number;
  error_summary: string | null;
  currencies: string[] | null;
  date_start: string | null;
  date_end: string | null;
  created_at: string;
  completed_at: string | null;
};

export type ImportDetail = ImportSummary & { errors: ImportRowError[] | null };

export type CanonicalField = {
  name: string;
  required: boolean;
  description: string;
  example: string;
  accepted_headers: string[];
};

export type ImportSchema = {
  fields: CanonicalField[];
  max_upload_bytes: number;
  max_rows: number;
};

// --- costs -------------------------------------------------------------------

export type DataStatus = {
  has_data: boolean;
  currencies: string[];
  default_currency: string | null;
  data_start: string | null;
  data_end: string | null;
  has_sample_data: boolean;
  record_count: number;
};

export type PeriodTotal = {
  start: string;
  end: string;
  total_cost: Money;
  days_in_period: number;
  days_with_data: number;
};

export type CostSummary = {
  currency: string;
  as_of: string | null;
  current: PeriodTotal;
  previous: PeriodTotal;
  change_abs: Money | null;
  change_pct: number | null;
  daily_average: Money | null;
  missing_days: string[];
};

export type Granularity = "day" | "week" | "month";

export type SeriesPoint = {
  period_start: string;
  period_end: string;
  cost: Money | null;
  days_in_period: number;
  days_with_data: number;
  is_partial: boolean;
};

export type Timeseries = {
  currency: string;
  granularity: Granularity;
  start: string;
  end: string;
  points: SeriesPoint[];
};

export type BreakdownItem = {
  key: string | null;
  label: string;
  cost: Money;
  share_pct: number | null;
  previous_cost: Money;
  change_abs: Money;
  change_pct: number | null;
};

export type Breakdown = {
  currency: string;
  dimension: Dimension;
  start: string;
  end: string;
  previous_start: string;
  previous_end: string;
  total_cost: Money;
  items: BreakdownItem[];
  other_cost: Money;
  other_count: number;
};

export type Forecast = {
  currency: string;
  month_start: string;
  month_end: string;
  as_of: string | null;
  actual_to_date: Money;
  days_elapsed: number;
  days_remaining: number;
  days_in_month: number;
  missing_days_to_date: number;
  trailing_daily_median: Money | null;
  trailing_days_used: number;
  forecast_total: Money | null;
  previous_month_total: Money | null;
  previous_month_complete: boolean;
  status: "ok" | "insufficient_data" | "complete" | "no_data";
  message: string;
  assumptions: string[];
};

// --- allocation rules ----------------------------------------------------------

export type MatchField = "provider" | "account_id" | "service" | "resource_id" | "region" | "usage_type";

export type AllocationRuleInput = {
  name: string;
  match_field: MatchField;
  match_operator: "equals" | "prefix" | "contains";
  match_value: string;
  project: string | null;
  environment: string | null;
  priority: number;
  enabled: boolean;
};

export type AllocationRule = AllocationRuleInput & {
  id: number;
  created_at: string;
  updated_at: string;
};

export type AllocationRuleMutation = { rule: AllocationRule | null; records_updated: number };

// --- anomaly detection -----------------------------------------------------------

export type DetectionSettings = {
  pct_threshold: string;
  abs_threshold: string;
  z_threshold: string;
  new_spend_threshold: string;
  min_history_days: number;
  baseline_window_days: number;
  evaluation_window_days: number;
  severity_medium_pct: string;
  severity_high_pct: string;
  severity_critical_pct: string;
  severity_medium_abs: string;
  severity_high_abs: string;
  severity_critical_abs: string;
  scopes: ScopeType[];
  updated_at: string;
};

export type DetectionRun = {
  id: number;
  trigger: string;
  status: "running" | "completed" | "failed";
  started_at: string;
  finished_at: string | null;
  currencies: string[] | null;
  evaluation_start: string | null;
  evaluation_end: string | null;
  series_evaluated: number;
  points_evaluated: number;
  points_insufficient_history: number;
  anomalies_detected: number;
  incidents_created: number;
  notes: string[] | null;
  error: string | null;
};

export type IncidentSummary = {
  id: number;
  title: string;
  status: IncidentStatus;
  severity: Severity;
  kind: "spike" | "new_spend";
  currency: string;
  scope_type: ScopeType;
  scope_value: string;
  start_date: string;
  end_date: string;
  observed_cost: Money;
  expected_cost: Money;
  deviation_abs: Money;
  peak_deviation_pct: string | null;
  detection_count: number;
  created_at: string;
  updated_at: string;
};

export type Detection = {
  id: number;
  anomaly_date: string;
  kind: "spike" | "new_spend";
  severity: Severity;
  observed_cost: Money;
  expected_cost: Money;
  deviation_abs: Money;
  deviation_pct: string | null;
  z_score: string | null;
  baseline_method: string;
  baseline_points: number;
  thresholds: Record<string, string>;
  evidence: {
    baseline_values: [string, string][];
    history_days: number;
    spread: string | null;
    reason: string;
  };
  first_detected_at: string;
  last_evaluated_at: string;
};

export type IncidentEvent = {
  id: number;
  event_type: string;
  actor: string;
  message: string;
  created_at: string;
};

export type IncidentDetail = IncidentSummary & {
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  resolved_at: string | null;
  resolved_by: string | null;
  resolution_note: string | null;
  detections: Detection[];
  events: IncidentEvent[];
};

export type IncidentCounts = Record<IncidentStatus, number>;

export type UsageDriver = "usage" | "rate" | "mixed" | "mixed_units" | "new" | "unknown";

export type Contributor = {
  key: string | null;
  label: string;
  current_cost: Money;
  baseline_cost: Money;
  baseline_daily_avg: Money;
  current_daily_avg: Money;
  change: Money;
  share_of_increase_pct: number | null;
  is_new: boolean;
  usage: {
    unit: string | null;
    baseline_daily_quantity: string | null;
    current_daily_quantity: string | null;
    quantity_ratio: number | null;
    cost_ratio: number | null;
    driver: UsageDriver;
  } | null;
};

export type Investigation = {
  incident_id: number;
  currency: string;
  scope_label: string;
  current_start: string;
  current_end: string;
  current_days_with_data: number;
  baseline_start: string;
  baseline_end: string;
  baseline_days_with_data: number;
  current_total: Money;
  baseline_daily_avg: Money | null;
  expected_total_from_baseline: Money | null;
  total_change: Money | null;
  observed_cost: Money;
  expected_cost: Money;
  deviation_abs: Money;
  peak_deviation_pct: string | null;
  confidence: "high" | "medium" | "low";
  confidence_statement: string;
  summary: string[];
  explanations: string[];
  suggestions: { title: string; detail: string; evidence: string }[];
  limitations: string[];
  dimensions: {
    dimension: Dimension;
    label: string;
    contributors: Contributor[];
    other_change: Money;
    members_total: number;
  }[];
  chart: { day: string; cost: Money | null; expected: Money | null; is_anomaly: boolean }[];
  related_incidents: {
    id: number;
    title: string;
    status: IncidentStatus;
    severity: Severity;
    start_date: string;
    end_date: string;
  }[];
};

// --- budgets & notifications -------------------------------------------------------

export type BudgetPeriod = "monthly" | "quarterly" | "yearly";

export type BudgetInput = {
  name: string;
  amount: string;
  currency: string;
  period: BudgetPeriod;
  scope_type: ScopeType;
  scope_value: string;
  thresholds: number[];
  renotify_hours: number | null;
  enabled: boolean;
};

export type Budget = BudgetInput & { id: number; created_at: string; updated_at: string };

export type BudgetStatus = {
  budget: Budget;
  as_of: string | null;
  period_start: string | null;
  period_end: string | null;
  actual: Money;
  utilization_pct: string | null;
  projected_total: Money | null;
  projected_utilization_pct: string | null;
  days_remaining: number | null;
  state: "no_data" | "ok" | "warning" | "over_budget";
  message: string;
  thresholds_crossed: number[];
};

export type BudgetAlert = {
  id: number;
  budget_id: number;
  period_start: string;
  period_end: string;
  threshold_pct: number;
  actual_amount: Money;
  budget_amount: Money;
  utilization_pct: string;
  data_as_of: string;
  crossed_at: string;
  last_notified_at: string | null;
  notification_count: number;
};

export type ChannelInput = {
  name: string;
  type: "webhook" | "email";
  target: string | null;
  enabled: boolean;
  notify_budget_alerts: boolean;
  notify_incidents: boolean;
  min_severity: Severity;
};

export type Channel = Omit<ChannelInput, "target"> & {
  id: number;
  target_display: string;
  created_at: string;
  updated_at: string;
};

export type Delivery = {
  id: number;
  channel_id: number | null;
  channel_name: string;
  channel_type: string;
  event_type: string;
  subject: string;
  status: "pending" | "sent" | "failed";
  attempts: number;
  last_error: string | null;
  created_at: string;
  last_attempt_at: string | null;
  sent_at: string | null;
};
