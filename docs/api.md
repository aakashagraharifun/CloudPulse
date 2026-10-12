# API reference

Base URL: `http://127.0.0.1:8000/api/v1`. The interactive OpenAPI documentation is at **http://127.0.0.1:8000/docs** (Swagger UI) and `/redoc`. The machine-readable spec is at `/api/v1/openapi.json`.

The examples use PowerShell's `curl.exe` (the real curl that ships with Windows; plain `curl` in PowerShell is an alias for `Invoke-WebRequest`).
JSON bodies are written as `'{\"key\":\"value\"}'`, which is the escaping Windows PowerShell 5.1 needs for native programs. In PowerShell 7.3 or later, remove the backslashes, or use `Invoke-RestMethod -Method Post -ContentType application/json -Body '{"key":"value"}'`.

## Authentication

Everything except `/health`, `/ready`, `/auth/status`, `/auth/setup`, `/auth/login` and `/imports/template.csv` requires a session token:

```powershell
# Sign in and keep the token (PowerShell)
$session = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/auth/login `
  -ContentType application/json -Body '{"email":"you@example.com","password":"your-password"}'
$auth = @{ Authorization = "Bearer $($session.token)" }
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/costs/summary -Headers $auth
```

With curl.exe, add `-H "Authorization: Bearer <token>"` to every example below.

| Method | Path | Who | Description |
| --- | --- | --- | --- |
| GET | `/auth/status` | public | `{"setup_required": true}` while no user exists |
| POST | `/auth/setup` | public | `{email, name, password}`. Creates the first **admin** (only while no user exists) and returns a session |
| POST | `/auth/login` | public | `{email, password}` returns `{token, token_type: "bearer", expires_at, user}`. Responds 401 `invalid_credentials` or 429 `account_locked` (with `Retry-After`) |
| GET | `/auth/me` | signed in | The current user |
| POST | `/auth/logout` | signed in | Revokes this token (204) |
| POST | `/auth/change-password` | signed in | `{current_password, new_password}`. Signs out your other sessions |
| GET | `/users` | admin | List users |
| POST | `/users` | admin | `{email, name, role, password}` |
| PATCH | `/users/{id}` | admin | `{name?, role?, is_active?}`. You cannot demote or deactivate yourself, and the last active admin is protected (409) |
| POST | `/users/{id}/reset-password` | admin | `{password}`. Signs out that user's sessions |
| GET | `/audit-events?action=&limit=&offset=` | admin | Audit log, newest first |

**Roles.** `GET` endpoints need any signed-in user (viewer). Changing data needs **member**. These need **admin**: deleting imports, detection settings, allocation rules, notification channels (including test sends), users and the audit log. Missing or invalid tokens return `401` (`not_authenticated` / `invalid_token`, with `WWW-Authenticate: Bearer`). An insufficient role returns `403 forbidden`.

Passwords must be 10–128 characters, without leading or trailing spaces; otherwise the response is `422 weak_password`.

## Conventions

- **Money** is returned as a decimal string with 4 places, e.g. `"1234.5000"`. Parse it for display only.
- **Dates** are `YYYY-MM-DD` UTC calendar days. Timestamps are ISO 8601 UTC.
- **Currency:** analytics endpoints take `?currency=USD`. It may be omitted when the data contains exactly one currency. With several currencies and no parameter, the API returns `400 currency_required` and lists them in `details.currencies`.
- **Pagination:** list endpoints take `limit` and `offset` and return `{"items": [...], "total", "limit", "offset"}`.
- **Request IDs:** every response has an `X-Request-ID` header. Send your own (letters, digits, `._-`, up to 64 characters) to correlate logs. A 500 response includes it in `error.details.request_id`.
- **Errors** always use one envelope:

```json
{ "error": { "code": "validation_error", "message": "The request is invalid.", "details": [ { "location": "query.currency", "message": "String should match pattern '^[A-Za-z]{3}$'" } ] } }
```

| Status | `code` examples |
| --- | --- |
| 400 | `currency_required`, `invalid_date_range` |
| 401 | `not_authenticated`, `invalid_token`, `invalid_credentials` |
| 403 | `forbidden` (role too low) |
| 404 | `not_found`, `no_data` |
| 409 | `conflict` (duplicate file, sample already loaded), `invalid_transition` |
| 413 | `file_too_large` |
| 415 | `unsupported_file_type` |
| 422 | `validation_error`, `import_validation_failed`, `weak_password` |
| 429 | `account_locked` |
| 500 | `internal_error` (details are logged, never returned; `details.request_id` identifies the log entry) |

## Health

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | Liveness check. Returns 200 while the process runs |
| GET | `/ready` | Readiness check. Verifies the database and Redis; returns 503 if either is down |

```powershell
curl.exe http://127.0.0.1:8000/api/v1/ready
# {"status":"ready","database":{"status":"ok","detail":null},"redis":{"status":"ok","detail":null}}
```

## Imports

| Method | Path | Description |
| --- | --- | --- |
| POST | `/imports` | Upload a CSV (`multipart/form-data`: `file`, optional `is_sample=true`) |
| POST | `/imports/sample` | Load the built-in synthetic dataset. If an older version is loaded, only the records new in this version are added for the same dates. 409 if it is already complete, or if the loaded sample does not match the built-in one (an update could double-count) |
| GET | `/imports` | List imports, newest first |
| GET | `/imports/{id}` | Status, counters and validation errors |
| DELETE | `/imports/{id}` | Delete an import **and all of its billing records** |
| GET | `/imports/schema` | Canonical fields, accepted header names, limits |
| GET | `/imports/template.csv` | A CSV template with one example row |

```powershell
curl.exe -F "file=@sample-data/synthetic_billing_90d.csv" -F "is_sample=true" http://127.0.0.1:8000/api/v1/imports
```

On success the API returns `201` with the import: `status: "completed"`, `rows_inserted`, `rows_duplicate`, `date_start`, `date_end` and `currencies`. Anomaly detection and budget checks run immediately afterwards.

If validation fails, the API returns `422 import_validation_failed`, and `error.details` holds the full import record including its errors:

```json
{"error":{"code":"import_validation_failed",
 "message":"5 rows failed validation (5 problems). No records were imported; fix the file and upload it again.",
 "details":{"id":3,"status":"failed","rows_invalid":5,"errors":[
   {"line":3,"column":"usage_date","message":"'09/02/2026' is not an ISO 8601 date. Use YYYY-MM-DD (e.g. 2026-01-31) or a timestamp such as 2026-01-31T00:00:00Z."},
   {"line":4,"column":"cost","message":"'1,038.42' contains a comma. Use '.' as the decimal separator and no thousands separators."}]}}}
```

Uploading a file identical to a completed import returns `409`: `"This file was already imported as import #1 (…). No records were added."`

## Costs

Common query parameters: `currency`, `start`, `end` (inclusive; defaults to the 30 days ending on the latest day with data), plus exact-match filters `provider`, `account_id`, `service`, `region`, `resource_id`, `usage_type`, `model`, `project` and `environment`, and `category` (`cloud`, `ai`, `saas` or `other`, derived from the provider). Pass the value `(unassigned)` to select records where a dimension is missing.

`dimension` (breakdowns, detection scopes and budget scopes) is one of `provider`, `category`, `account_id`, `service`, `region`, `resource_id`, `usage_type`, `model`, `project` or `environment`. For `category`, `label` is the display name (for example `AI & LLM APIs`).

| Method | Path | Description |
| --- | --- | --- |
| GET | `/costs/data-status` | Loaded currencies, date coverage, `has_sample_data` |
| GET | `/costs/summary` | Total for the period, the previous equal-length period, change, daily average, missing days |
| GET | `/costs/timeseries?granularity=day\|week\|month` | Cost per period. `cost` is null when no billing data exists; `is_partial` flags clipped or incomplete periods |
| GET | `/costs/breakdown?dimension=service&limit=10` | Ranked members with share, previous cost and change. The remainder is rolled into `other_cost` |
| GET | `/costs/forecast` | Month-end projection with status, message and assumptions |

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/costs/breakdown?dimension=service&start=2026-10-07&end=2026-10-08&limit=3"
```

```json
{"currency":"USD","dimension":"service","start":"2026-10-07","end":"2026-10-08",
 "previous_start":"2026-10-05","previous_end":"2026-10-06","total_cost":"1685.4831",
 "items":[{"key":"Amazon Elastic Compute Cloud","label":"Amazon Elastic Compute Cloud","cost":"1501.6332",
   "share_pct":89.09,"previous_cost":"125.1840","change_abs":"1376.4492","change_pct":1099.54}, "…"],
 "other_cost":"105.6429","other_count":8}
```

## Allocation rules

| Method | Path | Description |
| --- | --- | --- |
| GET | `/allocation-rules` | List rules (priority order) |
| POST | `/allocation-rules` | Create a rule; returns `{rule, records_updated}` after re-attributing existing records |
| PUT | `/allocation-rules/{id}` | Replace a rule (re-attributes) |
| DELETE | `/allocation-rules/{id}` | Delete a rule (re-attributes); returns `{rule: null, records_updated}` |

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/allocation-rules -H "Content-Type: application/json" `
  -d '{\"name\":\"NAT is platform\",\"match_field\":\"resource_id\",\"match_operator\":\"prefix\",\"match_value\":\"nat-\",\"project\":\"platform\",\"environment\":\"production\"}'
```

## Anomaly detection

| Method | Path | Description |
| --- | --- | --- |
| GET | `/anomalies/settings` | Current thresholds and scopes |
| PUT | `/anomalies/settings` | Replace thresholds (validated: e.g. `min_history_days ≤ baseline_window_days`, increasing severity levels) |
| POST | `/anomalies/runs` | Run detection now; returns the run summary |
| GET | `/anomalies/runs` | Run history |

```json
{"id":2,"trigger":"manual","status":"completed","evaluation_start":"2026-09-28","evaluation_end":"2026-10-11",
 "series_evaluated":12,"points_evaluated":168,"points_insufficient_history":0,
 "anomalies_detected":6,"incidents_created":0,"notes":null,"error":null, "settings_snapshot":{"…":"…"}}
```

## Incidents and investigation

| Method | Path | Body | Description |
| --- | --- | --- | --- |
| GET | `/incidents?status=open&severity=high` | | Unresolved first, then most recent and most severe |
| GET | `/incidents/counts` | | `{open, acknowledged, resolved}` |
| GET | `/incidents/{id}` | | Incident with `detections` (all evidence) and `events` (timeline) |
| GET | `/incidents/{id}/investigation` | | Contributors, explanations, suggestions, limitations, chart data, related incidents |
| POST | `/incidents/{id}/acknowledge` | `{"note": null}` | `open` → `acknowledged` |
| POST | `/incidents/{id}/resolve` | `{"resolution_note": "…"}` | Requires a note |
| POST | `/incidents/{id}/reopen` | `{"reason": null}` | `resolved` → `open` |
| POST | `/incidents/{id}/notes` | `{"body": "…"}` | Adds a timeline note (201) |

The acting user recorded on the timeline is always the signed-in user. Any `actor` field in the body is ignored.

Invalid transitions (for example acknowledging a resolved incident) return `409 invalid_transition`.

Excerpt of an investigation:

```json
{"confidence":"high",
 "confidence_statement":"The increase is concentrated in resource 'i-0f3e9a7c5b1d2468a' (100.0% of the change). Billing data shows where the money went, not why; confirm the reason with the owning team.",
 "explanations":["Resource 'i-0f3e9a7c5b1d2468a' had no cost in the baseline period and contributed 1,376.45 USD of the 1,376.45 USD increase (100.0%), averaging 688.22 USD per day during the incident."],
 "suggestions":[{"title":"Confirm resource i-0f3e9a7c5b1d2468a is expected",
   "detail":"Check who created it, whether it is still needed, and that it is tagged with an owner and project.",
   "evidence":"It first incurred cost during the incident (2026-10-07 to 2026-10-08) with no baseline spend."}],
 "dimensions":[{"dimension":"resource_id","contributors":[{"key":"i-0f3e9a7c5b1d2468a","change":"1376.4492",
   "share_of_increase_pct":100.0,"is_new":true,"usage":{"driver":"new","unit":"Hrs"}}]}]}
```

## Budgets

| Method | Path | Description |
| --- | --- | --- |
| GET | `/budgets` | All budgets with live status: `actual`, `utilization_pct`, `projected_total`, `state`, `thresholds_crossed` |
| POST | `/budgets` | Create |
| GET / PUT / DELETE | `/budgets/{id}` | Read, replace, delete (alert history is deleted with the budget) |
| POST | `/budgets/evaluate` | Check every budget now and send due alerts; returns `{notifications_sent}` |
| GET | `/budgets/alerts?budget_id=` | Threshold-crossing history |

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/budgets -H "Content-Type: application/json" `
  -d '{\"name\":\"Monthly cloud budget\",\"amount\":\"3000\",\"currency\":\"USD\",\"period\":\"monthly\",\"scope_type\":\"total\",\"thresholds\":[50,80,100]}'
```

Fields: `period` is `monthly`, `quarterly` or `yearly`. `scope_type` is `total` or a dimension, and `scope_value` is required for a dimension. `thresholds` are integers from 1 to 1000. `renotify_hours` is null (alert once per threshold per period) or a number of hours between repeats.

## Notifications

| Method | Path | Description |
| --- | --- | --- |
| GET | `/notifications/channels` | Channels (webhook URLs masked in `target_display`) |
| POST | `/notifications/channels` | Create `{name, type: "email"\|"webhook", target, notify_budget_alerts, notify_incidents, min_severity, enabled}` |
| PUT | `/notifications/channels/{id}` | Update. Omit `target` to keep the existing one |
| DELETE | `/notifications/channels/{id}` | Delete (delivery history is kept) |
| POST | `/notifications/channels/{id}/test` | Send a test message now and return the delivery record (`status: sent` or `failed` with `last_error`) |
| GET | `/notifications/deliveries` | Every delivery attempt |

Webhook payload (JSON `POST`; the top-level `text` field renders in Slack or Teams incoming webhooks):

```json
{"source":"cloudpulse","event":"budget_threshold",
 "subject":"[CloudPulse] Budget 'Monthly cloud budget' reached 100.28% (threshold 100%)",
 "text":"[CloudPulse] Budget …\nBudget: Monthly cloud budget (Total spend)\n…",
 "data":{"budget_id":1,"threshold_pct":100,"utilization_pct":"100.28","actual":"3008.36868300","amount":"3000.00000000","currency":"USD","period_start":"2026-10-01","as_of":"2026-10-11"}}
```

Event types: `budget_threshold`, `incident_opened` and `test`.
