# Database schema

PostgreSQL 16, managed with Alembic migrations in `backend/alembic/versions/`:

| Revision | Creates |
| --- | --- |
| `0001` | `billing_imports`, `billing_records`, `allocation_rules` |
| `0002` | `detection_settings`, `detection_runs`, `anomaly_detections`, `incidents`, `incident_events`, `budgets`, `budget_alerts`, `notification_channels`, `notification_deliveries` |
| `0003` | `users`, `user_sessions`, `audit_events` |
| `0004` | `billing_records.model` (+ index); allocation rules may match on `model` |

Conventions:
- Money is `NUMERIC(18,8)` and quantities are `NUMERIC(24,8)`. Floating point is never used for money.
- Timestamps are `timestamptz` (UTC). Billing days are `date` and represent UTC calendar days.
- Constraint names follow a fixed naming convention (`pk_`, `fk_`, `uq_`, `ck_`, `ix_`) so migrations stay readable.
- Status and enumeration columns are `VARCHAR` with `CHECK` constraints rather than PostgreSQL enums, which are easier to evolve.

## Relationships

```
billing_imports 1───* billing_records          (ON DELETE CASCADE)
allocation_rules        (applied to billing_records.project / environment)

detection_settings      (single row, id = 1)
detection_runs 1───* anomaly_detections        (ON DELETE SET NULL)
incidents      1───* anomaly_detections        (ON DELETE SET NULL)
incidents      1───* incident_events           (ON DELETE CASCADE)

budgets        1───* budget_alerts             (ON DELETE CASCADE)
notification_channels 1───* notification_deliveries (ON DELETE SET NULL, history kept)

users          1───* user_sessions             (ON DELETE CASCADE)
users          1───* audit_events              (actor; ON DELETE SET NULL, e-mail kept)
```

## Billing

### `billing_imports`
One row per upload attempt, whatever its outcome.

| Column | Notes |
| --- | --- |
| `id` | PK |
| `filename` | Sanitized display name (never used as a path) |
| `source` | `upload` \| `sample` \| `connector`. Sample data is labelled in the UI |
| `connector_id` | FK → `connectors` (SET NULL); set for connector syncs |
| `file_sha256`, `file_size_bytes` | File identity |
| `detected_format` | `cloudpulse` \| `aws_cur` \| `aws_cost_explorer` \| `openai_costs` \| `anthropic_cost_report` |
| `status` | `processing` \| `completed` \| `failed` |
| `rows_total`, `rows_inserted`, `rows_duplicate`, `rows_invalid` | Outcome counters |
| `rows_replaced` | Connector syncs: stale records of earlier syncs removed from the sync window |
| `errors` (JSONB) | Up to 200 `{line, column, message}` entries |
| `error_summary` | Human-readable summary |
| `currencies` (JSONB), `date_start`, `date_end` | What the file contained |
| `created_at`, `updated_at`, `completed_at` | |

The partial unique index `uq_billing_imports_completed_sha256` on `file_sha256 WHERE status = 'completed' AND source <> 'connector'` means the same file can be completed only once, while failed attempts can be retried. Connector syncs are exempt because a provider can restate data back to an earlier state; they are reconciled per sync window instead.

### `connectors`
One configured live billing connector.

| Column | Notes |
| --- | --- |
| `id` | PK |
| `kind` | `aws_cur_s3` \| `aws_cost_explorer` \| `openai_costs` \| `anthropic_costs` |
| `name`, `enabled` | |
| `config` (JSONB) | Non-secret settings (bucket, region, prefix, grouping, role ARN, …) |
| `credentials_encrypted` | Fernet token of the credentials JSON; the key lives only in `CONNECTOR_ENCRYPTION_KEY` |
| `credentials_hint` | Masked form for display, e.g. `sk-ant-…3456` |
| `sync_interval_hours` | 0 (manual) to 168 |
| `lookback_days` | 1 to 365; the window each sync re-reads (CUR uses `config.billing_periods`) |
| `last_verified_at`, `verified_identity` | Last successful credential check, and who the provider says the key belongs to |
| `last_sync_status`, `last_sync_started_at`, `last_sync_finished_at`, `last_sync_message` | `running` \| `succeeded` \| `failed`; a `running` sync older than an hour is treated as crashed |
| `last_import_id` | FK → `billing_imports` (SET NULL) of the last sync that changed data |
| `created_by_id` | FK → `users` (SET NULL) |
| `created_at`, `updated_at` | |

### `billing_records`
The canonical billing model: one normalized line item per row.

| Column | Notes |
| --- | --- |
| `id` | PK (bigint) |
| `import_id` | FK → `billing_imports.id`, cascade delete |
| `usage_date` | UTC day the cost was incurred |
| `provider`, `account_id`, `service`, `resource_id`, `region`, `usage_type` | Dimensions (`service` and `provider` required) |
| `model` | AI/LLM model for model-usage line items (e.g. `gpt-4o`), otherwise null. Indexed. Included in the fingerprint only when present, so fingerprints of records without a model are unchanged |
| `usage_quantity`, `usage_unit` | Optional usage (for AI usage: tokens). Enables usage-versus-price analysis |
| `currency` | ISO 4217 code; `CHECK (currency ~ '^[A-Z]{3}$')` |
| `cost` | `NUMERIC(18,8)`. Negative values (credits) are allowed |
| `project_tag`, `environment_tag` | Tags exactly as they appeared in the source file |
| `project`, `environment` | Effective attribution: the tag, otherwise the first matching allocation rule |
| `source_row_number` | Physical line number in the uploaded file (traceability) |
| `extra_attributes` (JSONB) | Unmapped source columns (up to 50, 256 chars each) |
| `fingerprint` | SHA-256 of the canonical values plus an occurrence index. **UNIQUE** |
| `created_at` | |

Indexes: `(currency, usage_date)`, `(usage_date, service)`, `import_id`, `project`.

### `allocation_rules`
Rules are evaluated by ascending `priority`, then `id`. They are case-insensitive.

| Column | Notes |
| --- | --- |
| `match_field` | `provider`, `account_id`, `service`, `resource_id`, `region`, `usage_type` or `model` |
| `match_operator` | `equals`, `prefix` or `contains` |
| `match_value` | |
| `project`, `environment` | At least one must be set (`CHECK`) |
| `priority`, `enabled`, `name`, timestamps | |

## Anomaly detection and incidents

### `detection_settings`
A single row (`CHECK (id = 1)`) with every threshold described in [anomaly-detection.md](anomaly-detection.md): `pct_threshold`, `abs_threshold`, `z_threshold`, `new_spend_threshold`, `min_history_days`, `baseline_window_days`, `evaluation_window_days`, six severity thresholds, and `scopes` (JSONB list such as `["total", "service"]`).

### `detection_runs`
Audit of every run: `trigger` (`manual`, `post_import` or `scheduled`), `status`, timings, a `settings_snapshot` (JSONB copy of the thresholds used), the evaluation window, counters (`series_evaluated`, `points_evaluated`, `points_insufficient_history`, `anomalies_detected`, `incidents_created`), `notes` (insufficient-history explanations) and `error`.

### `anomaly_detections`
One anomalous (currency, scope, day) with its evidence. **UNIQUE** `(currency, scope_type, scope_value, anomaly_date)` (named `uq_detection_scope_day`), so re-running detection updates the row instead of duplicating it.

| Column | Notes |
| --- | --- |
| `run_id` | FK → last run that evaluated it |
| `incident_id` | FK → incident it belongs to |
| `scope_type`, `scope_value` | `total` with `""`, or a dimension and its value (`(unassigned)` for missing values) |
| `kind`, `severity` | `spike` \| `new_spend`; `low` … `critical` |
| `observed_cost`, `expected_cost`, `deviation_abs` | Money |
| `deviation_pct`, `z_score` | Null for new spend and flat baselines respectively |
| `baseline_method`, `baseline_points` | `day_of_week_median` \| `rolling_median` |
| `thresholds` (JSONB) | Thresholds in force when the decision was made |
| `evidence` (JSONB) | Baseline values, history days, spread, reason text |
| `first_detected_at`, `last_evaluated_at` | |

### `incidents`
One cost event for one scope. Consecutive anomalous days are grouped.

| Column | Notes |
| --- | --- |
| `title`, `status` (`open`/`acknowledged`/`resolved`), `severity`, `kind` | |
| `currency`, `scope_type`, `scope_value`, `start_date`, `end_date` | |
| `observed_cost`, `expected_cost`, `deviation_abs`, `peak_deviation_pct`, `detection_count` | Aggregated from detections |
| `acknowledged_at/by`, `resolved_at/by`, `resolution_note` | Workflow |

Indexes: `(currency, scope_type, scope_value, status)` for the de-duplication lookup, and `(status, start_date)`.

### `incident_events`
The timeline and audit trail: `event_type` (`created`, `detection_added`, `acknowledged`, `note`, `resolved` or `reopened`), `actor`, `message`, optional `data` (JSONB) and `created_at`.

## Budgets and notifications

### `budgets`
`name`, `amount` (`CHECK > 0`), `currency`, `period` (`monthly`, `quarterly` or `yearly`), `scope_type` and `scope_value` (`total` or a dimension), `thresholds` (JSONB list of percentages), `renotify_hours` (null means alert once per threshold per period), `enabled`, timestamps.

### `budget_alerts`
One row per threshold crossing. **UNIQUE** `(budget_id, period_start, threshold_pct)` guarantees a threshold alerts at most once per period (repeats only happen under the `renotify_hours` policy, using new event keys). Columns: `period_start`, `period_end`, `threshold_pct`, `actual_amount`, `budget_amount`, `utilization_pct`, `data_as_of`, `crossed_at`, `last_notified_at`, `notification_count`.

### `notification_channels`
`name`, `type` (`webhook` or `email`), `target` (URL or comma-separated addresses; masked in API responses for webhooks), `enabled`, `notify_budget_alerts`, `notify_incidents`, `min_severity`.

### `notification_deliveries`
Every attempt to notify a channel: `channel_id` (`SET NULL` on channel delete, so history is kept), `channel_name`, `channel_type`, `event_type`, `event_key`, `subject`, `body`, `payload` (JSONB), `status` (`pending`/`sent`/`failed`), `attempts`, `last_error`, timestamps. **UNIQUE** `(channel_id, event_key)` means the same event is never delivered twice to the same channel.

## Users, sessions and audit

### `users`
| Column | Notes |
| --- | --- |
| `email` | **UNIQUE**; `CHECK (email = lower(email))` so look-ups are case-insensitive |
| `name` | Display name, used as the actor on incident actions |
| `password_hash` | `scrypt$n$r$p$salt$hash`; never the password |
| `role` | `viewer` \| `member` \| `admin` (`CHECK`) |
| `is_active` | Deactivated users cannot sign in and lose their sessions |
| `failed_login_count`, `locked_until` | Lockout after repeated failures |
| `last_login_at`, timestamps | |

### `user_sessions`
`user_id` (FK, cascade), `token_hash` (SHA-256 of the bearer token, **UNIQUE**), `created_at`, `expires_at`, `last_used_at` (updated at most every 5 minutes), `revoked_at`, `user_agent`, `ip_address`. Sessions that expired or were revoked more than 7 days ago are purged daily by Celery.

### `audit_events`
`actor_user_id` (FK, `SET NULL`), `actor_email` (a snapshot, also used for failed logins with no user), `action` (indexed, e.g. `import.deleted`), `target_type`, `target_id`, `details` (JSONB), `ip_address`, `request_id`, `created_at` (indexed).

The data model is a **single workspace**: billing data is not partitioned per user or organization (see architecture.md, "Authentication and authorization").

## Provider categories

`category` is not stored. It is computed from `provider` in SQL (`app/services/providers.py`): known cloud providers map to `cloud`, model APIs (OpenAI, Anthropic, Google Gemini API, Mistral, DeepSeek, Hugging Face) to `ai`, SaaS and data platforms (Datadog, Snowflake, Databricks, MongoDB Atlas) to `saas`, and anything else to `other`. Changing the mapping therefore re-categorizes existing data without a migration.
