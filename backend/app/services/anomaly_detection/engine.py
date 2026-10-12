"""Explainable statistical anomaly detection for a single daily cost series.

For one day `d` of one series (e.g. "service = Amazon EC2", USD):

1. `d` must have billing data (coverage). Days with no data are never judged.
2. History = covered days in the `baseline_window_days` before `d`. With fewer
   than `min_history_days` of history the point is *not* evaluated and is
   reported as insufficient history - no anomaly is claimed.
3. Baseline (expected cost):
   * day-of-week median of the 4 most recent same-weekday covered days in the
     previous 8 weeks, when all 4 exist (handles weekday/weekend patterns);
   * otherwise the median of all history days ("rolling median").
   Medians are robust: one earlier spike does not distort the baseline.
4. Spread = MAD (median absolute deviation) x 1.4826, a robust standard
   deviation estimate; robust z = deviation / spread.
5. A *spike* requires ALL of:
   observed > expected > 0, deviation >= abs_threshold,
   deviation % >= pct_threshold, and robust z >= z_threshold
   (the z gate is skipped when spread is 0, i.e. a perfectly flat history, or
   when z_threshold is 0).
   *New spend* (expected <= 0, e.g. a service that had no cost before) requires
   observed >= new_spend_threshold; a percentage is undefined and not reported.
6. Only increases are detected. Negative costs (credits) never trigger alerts.
"""

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

ZERO = Decimal("0")
MAD_TO_SIGMA = Decimal("1.4826")
DOW_POINTS = 4
DOW_LOOKBACK_DAYS = 56


@dataclass(frozen=True)
class DetectionConfig:
    pct_threshold: Decimal = Decimal(25)
    abs_threshold: Decimal = Decimal(25)
    z_threshold: Decimal = Decimal(3)
    new_spend_threshold: Decimal = Decimal(50)
    min_history_days: int = 14
    baseline_window_days: int = 28
    severity_medium_pct: Decimal = Decimal(50)
    severity_high_pct: Decimal = Decimal(100)
    severity_critical_pct: Decimal = Decimal(300)
    severity_medium_abs: Decimal = Decimal(100)
    severity_high_abs: Decimal = Decimal(500)
    severity_critical_abs: Decimal = Decimal(2000)

    def thresholds(self) -> dict[str, str]:
        return {
            "pct_threshold": str(self.pct_threshold),
            "abs_threshold": str(self.abs_threshold),
            "z_threshold": str(self.z_threshold),
            "new_spend_threshold": str(self.new_spend_threshold),
            "min_history_days": str(self.min_history_days),
            "baseline_window_days": str(self.baseline_window_days),
        }


@dataclass
class PointEvaluation:
    day: date
    status: str  # "anomaly" | "normal" | "insufficient_history" | "no_data"
    observed: Decimal = ZERO
    expected: Decimal | None = None
    deviation_abs: Decimal | None = None
    deviation_pct: Decimal | None = None
    z_score: Decimal | None = None
    spread: Decimal | None = None
    method: str | None = None
    baseline: list[tuple[date, Decimal]] = field(default_factory=list)
    history_days: int = 0
    kind: str | None = None  # "spike" | "new_spend"
    severity: str | None = None
    reason: str = ""

    def evidence(self) -> dict[str, Any]:
        return {
            "baseline_values": [[d.isoformat(), str(v)] for d, v in self.baseline],
            "history_days": self.history_days,
            "spread": None if self.spread is None else str(self.spread),
            "reason": self.reason,
        }


def _round(value: Decimal, places: str = "0.01") -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_EVEN)


def classify_severity(
    config: DetectionConfig, deviation_abs: Decimal, deviation_pct: Decimal | None
) -> str:
    """Highest level whose percentage AND absolute thresholds are both met.

    New spend (no percentage) is classified on the absolute amount alone.
    """
    levels = (
        ("critical", config.severity_critical_pct, config.severity_critical_abs),
        ("high", config.severity_high_pct, config.severity_high_abs),
        ("medium", config.severity_medium_pct, config.severity_medium_abs),
    )
    for name, pct, amount in levels:
        pct_ok = deviation_pct is None or deviation_pct >= pct
        if pct_ok and deviation_abs >= amount:
            return name
    return "low"


def _money(value: Decimal) -> str:
    return f"{_round(value):,}"


def evaluate_point(
    series: dict[date, Decimal],
    covered: set[date],
    day: date,
    config: DetectionConfig,
) -> PointEvaluation:
    """Evaluate one day. `series` holds the scope's daily cost; missing covered days are 0."""
    if day not in covered:
        return PointEvaluation(day, "no_data", reason="No billing data for this day.")

    observed = series.get(day, ZERO)
    window_start = day - timedelta(days=config.baseline_window_days)
    history = sorted(d for d in covered if window_start <= d < day)
    if len(history) < config.min_history_days:
        return PointEvaluation(
            day,
            "insufficient_history",
            observed=observed,
            history_days=len(history),
            reason=(
                f"Only {len(history)} day(s) of history in the previous "
                f"{config.baseline_window_days} days; {config.min_history_days} are required "
                "before a baseline can be trusted."
            ),
        )

    dow_start = day - timedelta(days=DOW_LOOKBACK_DAYS)
    same_weekday = sorted(
        d for d in covered if dow_start <= d < day and d.weekday() == day.weekday()
    )[-DOW_POINTS:]
    if len(same_weekday) == DOW_POINTS:
        method, baseline_days = "day_of_week_median", same_weekday
    else:
        method, baseline_days = "rolling_median", history
    baseline = [(d, series.get(d, ZERO)) for d in baseline_days]
    values = [v for _, v in baseline]
    expected = statistics.median(values)
    spread = statistics.median(abs(v - expected) for v in values) * MAD_TO_SIGMA
    deviation = observed - expected

    result = PointEvaluation(
        day,
        "normal",
        observed=observed,
        expected=expected,
        deviation_abs=deviation,
        spread=spread,
        method=method,
        baseline=baseline,
        history_days=len(history),
    )

    if observed <= 0 or deviation <= 0:
        result.reason = "Cost is not above the expected baseline."
        return result

    if expected <= 0:
        if observed >= config.new_spend_threshold:
            result.status, result.kind = "anomaly", "new_spend"
            result.severity = classify_severity(config, deviation, None)
            result.reason = (
                f"New spend of {_money(observed)} where the baseline had no cost; the new-spend "
                f"threshold is {_money(config.new_spend_threshold)}."
            )
        else:
            result.reason = "New spend is below the new-spend threshold."
        return result

    pct = _round(deviation / expected * 100)
    result.deviation_pct = pct
    z = _round(deviation / spread) if spread > 0 else None
    result.z_score = z

    failed = []
    if deviation < config.abs_threshold:
        failed.append(f"increase {_money(deviation)} < {_money(config.abs_threshold)}")
    if pct < config.pct_threshold:
        failed.append(f"increase {pct}% < {config.pct_threshold}%")
    if config.z_threshold > 0 and z is not None and z < config.z_threshold:
        failed.append(f"robust z {z} < {config.z_threshold}")
    if failed:
        result.reason = "Below threshold: " + "; ".join(failed) + "."
        return result

    result.status, result.kind = "anomaly", "spike"
    result.severity = classify_severity(config, deviation, pct)
    z_text = f", robust z-score {z}" if z is not None else ", baseline had no variation"
    result.reason = (
        f"Observed {_money(observed)} vs expected {_money(expected)}: +{_money(deviation)} "
        f"(+{pct}%){z_text}. Thresholds: +{_money(config.abs_threshold)} and "
        f"+{config.pct_threshold}%"
        + (f" and z >= {config.z_threshold}." if config.z_threshold > 0 else ".")
    )
    return result
