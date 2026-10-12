# Anomaly detection and investigation

CloudPulse uses **explainable statistics**, not a black-box model. Every decision can be reproduced from the stored evidence: the observed cost, the expected baseline, the baseline values used, the thresholds in force, and the reason text.

Code: `backend/app/services/anomaly_detection/engine.py` (pure statistics), `…/service.py` (runs and incidents), `backend/app/services/investigation/service.py` (evidence and explanations).

## What is evaluated

A **series** is the daily cost of one *scope* in one currency:

- `total`: all spend.
- A dimension: one series per value. For example, *service* gives one series per service. A missing value forms its own series, called `(unassigned)`.

The default scopes are **total** and **service**. Project, environment, region, provider, account, usage type and resource can be enabled in **Settings → Anomaly detection**. Each run evaluates the most recent `evaluation_window_days` (default 14) ending at the latest day with data for that currency.

Detection runs:
- after every successful import that added records;
- every 6 hours (Celery beat, `crontab(minute=15, hour="*/6")`);
- on demand (**Incidents → Run detection now** or `POST /api/v1/anomalies/runs`).

## Algorithm for one day *d*

1. **Data required.** If no billing data at all exists for *d* in that currency, the day is not judged. Missing data is never treated as zero spend.
2. **History.** History is the covered days in the previous `baseline_window_days` (default 28). With fewer than `min_history_days` (default 14), the day is **not evaluated**. The run records it as *insufficient history* with an explanatory note, and **no anomaly is claimed**.
3. **Baseline (expected cost).**
   - **Day-of-week median:** the median of the 4 most recent same-weekday covered days in the last 8 weeks, used when all 4 exist. This handles weekday and weekend patterns. A Saturday is compared with Saturdays.
   - Otherwise a **rolling median** of all history days is used.
   - The median is robust: one earlier spike does not inflate the baseline.
   - On covered days where a scope has no records (for example, a service that did not exist yet), its cost is a genuine **0**.
4. **Spread.** The MAD (median absolute deviation) × 1.4826 approximates a standard deviation without being distorted by outliers. The robust z-score is deviation ÷ spread.
5. **Decision.** A day is anomalous when **all** of these hold:

| Kind | Conditions |
| --- | --- |
| **Spike** | observed > expected > 0 **and** observed − expected ≥ `abs_threshold` (default 25) **and** % increase ≥ `pct_threshold` (default 25%) **and** robust z ≥ `z_threshold` (default 3) |
| **New spend** | expected ≤ 0 **and** observed ≥ `new_spend_threshold` (default 50). The percentage is undefined and is not reported |

   - The z gate is skipped when spread = 0 (a perfectly flat history, such as a fixed-price instance), because any increase is then outside normal variation. The percentage and amount gates still apply. Setting `z_threshold = 0` disables the z gate.
   - **Only increases are detected.** Decreases and negative costs (credits) never trigger alerts.
   - Division by zero cannot occur: percentages are only computed when expected > 0.
6. **Severity.** Severity is the highest level whose percentage **and** amount thresholds are both met. A large percentage on a tiny amount, or a large amount that is a small percentage, stays low.

| Level | % increase ≥ | Amount ≥ (defaults) |
| --- | --- | --- |
| critical | 300 | 2,000 |
| high | 100 | 500 |
| medium | 50 | 100 |
| low | everything else that passed detection | |

   New spend is classified on the amount alone.

### Persisted evidence

Every anomalous day is stored in `anomaly_detections` with `observed_cost`, `expected_cost`, `deviation_abs`, `deviation_pct`, `z_score`, `baseline_method`, `baseline_points`, `thresholds` (a copy), `evidence` (baseline dates and values, history size, spread, reason) and `last_evaluated_at`. Each run's settings snapshot and counters are stored in `detection_runs`.

## Incidents and de-duplication

- A detection is **unique per (currency, scope, day)**. Re-running detection updates it in place.
- A new anomalous day **joins an unresolved incident of the same scope** when it is adjacent to or inside that incident's dates. Otherwise it opens a new incident. Consecutive spike days therefore form one incident.
- Days already attached to a **resolved** incident are updated but never reopen or duplicate it. A *new* anomalous day after resolution opens a new incident.
- A PostgreSQL advisory lock serializes runs, so concurrent runs cannot both create an incident.
- New incidents notify every enabled channel whose `min_severity` is at or below the incident's severity.

The same event can appear in several scopes (for example *Total spend* and *Service: EC2*). These are separate incidents, and each investigation lists the others under **Related incidents**.

## Investigation

For an incident covering days *S…E*:

- **Baseline period:** the `baseline_window_days` days before *S*. Averages use only days that have data.
- For each member of each relevant dimension (service, resource, region, usage type, project, account; the incident's own dimension is excluded):
  `change = cost(S…E) − baseline daily average × number of incident days`
- Contributors are ranked by change and show their **share of the total increase**. Members with no baseline cost are flagged **new**.
- **Usage versus price.** This is only computed for resources and usage types whose rows all have a quantity in a single unit.

| Driver | Rule |
| --- | --- |
| usage-driven | quantity ratio ≥ 1.1 and the cost ratio is within ±15% of it |
| rate / price change | quantity ratio within 0.9–1.1 and cost ratio ≥ 1.1 |
| mixed | anything else with comparable quantities |
| several units | quantities are in different units, so they are not comparable |
| usage not available | quantities are missing, so the cause type cannot be determined (stated explicitly) |

- **Explanations** are fixed sentence templates filled with measured values. Contributors below 10% of the increase stay in the tables but are not narrated individually.
- **Suggestions** are only produced from evidence: a new resource ("confirm it is expected"), a new region, a usage-driven increase, a rate change, a usage type whose name indicates data transfer, or a large share of untagged spend. Each suggestion carries an **Evidence** line.
- **Confidence:**
  - *high*: the top contributor explains ≥ 80% of the increase.
  - *medium*: it explains 50–80%.
  - *low*: no single contributor explains most of it. The text then says that the billing data alone does not identify a single cause.
  - Even at high confidence, the text states that billing data shows *where* money went, not *why*.

## The sample dataset

The synthetic dataset (`backend/app/services/ingestion/sample_data.py`) produces exactly four incidents with the default settings. `tests/test_incidents.py` verifies this:

| Incident | Dates (relative to end) | Why |
| --- | --- | --- |
| Total spend, low | end − 11 | NAT bytes ≈ 8× (+$52, +34%) |
| Service: Amazon Virtual Private Cloud, low | end − 11 | Same event, +$50 (+672%), below the $100 amount for medium |
| Total spend, high | end − 4 … end − 3 | New p4d.24xlarge GPU instance (+$1,379) |
| Service: Amazon Elastic Compute Cloud, high | end − 4 … end − 3 | Same event (+$1,376, 100% one new resource) |

Normal noise (±4–10%), weekend dips and +0.2%/day growth produce **no** false positives.

## Tuning

| Symptom | Adjust |
| --- | --- |
| Too many small alerts | Raise `abs_threshold` (amount in your currency) |
| Noisy services alert often | Raise `z_threshold` |
| New projects alert immediately | Raise `new_spend_threshold` |
| Want earlier detection on new accounts | Lower `min_history_days`; the baseline becomes less reliable |
| Severity too high or too low | Adjust the severity % and amount pairs |

## Limitations

- **Daily granularity only.** Intra-day spikes are only visible as daily totals.
- **Increases only.** Unexpected drops (for example a service that stopped running) are not alerted.
- **No seasonality beyond the week.** Month-end batch jobs or yearly patterns can look anomalous. Use the thresholds, or resolve with a note.
- **History requirement.** New data sources produce no detections until `min_history_days` of data exist. Runs report this explicitly.
- **No automatic withdrawal.** If imported data is deleted or corrected, previously recorded detections remain until the incident is resolved.
- **Evaluation window.** Only the most recent `evaluation_window_days` are evaluated per run. Importing older history does not back-fill detections for older dates.
- **Billing data cannot explain intent.** CloudPulse identifies *what* changed (resource, region, usage type, quantity versus price). The *why* (a deployment, a test, a misconfiguration) must be confirmed by people. The confidence statement says so.
- **Each currency is evaluated separately.** There is no conversion.
