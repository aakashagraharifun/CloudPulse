"""Unit tests for the statistical detection engine (no database)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.services.anomaly_detection.engine import (
    DetectionConfig,
    classify_severity,
    evaluate_point,
)

CONFIG = DetectionConfig()
DAY = date(2026, 9, 30)  # a Wednesday


def build(values_before: list[float | None], value_on_day: float | None):
    """Series ending on DAY; None means the day has no billing data at all."""
    series: dict[date, Decimal] = {}
    covered: set[date] = set()
    all_values = [*values_before, value_on_day]
    start = DAY - timedelta(days=len(values_before))
    for offset, value in enumerate(all_values):
        day = start + timedelta(days=offset)
        if value is not None:
            covered.add(day)
            series[day] = Decimal(str(value))
    return series, covered


def test_flat_history_and_spike_is_detected_without_z_gate() -> None:
    series, covered = build([100.0] * 28, 300.0)
    result = evaluate_point(series, covered, DAY, CONFIG)
    assert result.status == "anomaly"
    assert result.kind == "spike"
    assert result.expected == Decimal(100)
    assert result.deviation_abs == Decimal(200)
    assert result.deviation_pct == Decimal("200.00")
    assert result.z_score is None  # no variation in the baseline
    assert result.method == "day_of_week_median"
    assert result.severity == "medium"  # 200% and +200 meet medium (50%/100), not high (+500)


def test_normal_variation_is_not_flagged() -> None:
    history = [100.0 + (i % 5) * 4 for i in range(28)]  # 100..116
    series, covered = build(history, 118.0)
    result = evaluate_point(series, covered, DAY, CONFIG)
    assert result.status == "normal"
    assert "Below threshold" in result.reason


def test_all_thresholds_must_pass() -> None:
    # +30% but only +3 in absolute terms: below the 25 absolute threshold.
    series, covered = build([10.0] * 28, 13.0)
    result = evaluate_point(series, covered, DAY, CONFIG)
    assert result.status == "normal"
    assert "increase 3.00 < 25.00" in result.reason


def test_z_gate_suppresses_spikes_inside_normal_noise() -> None:
    noisy = [100.0, 160.0, 90.0, 170.0] * 7
    series, covered = build(noisy, 175.0)
    config = DetectionConfig(pct_threshold=Decimal(10), abs_threshold=Decimal(10))
    result = evaluate_point(series, covered, DAY, config)
    assert result.status == "normal"
    assert "robust z" in result.reason


def test_insufficient_history_is_never_an_anomaly() -> None:
    series, covered = build([100.0] * 5, 10_000.0)
    result = evaluate_point(series, covered, DAY, CONFIG)
    assert result.status == "insufficient_history"
    assert result.history_days == 5
    assert "required" in result.reason


def test_missing_days_do_not_count_as_history() -> None:
    history: list[float | None] = [100.0 if i % 2 else None for i in range(28)]  # 14 covered
    series, covered = build(history, 500.0)
    assert evaluate_point(series, covered, DAY, CONFIG).status == "anomaly"
    history[1] = None  # now only 13 covered days
    series, covered = build(history, 500.0)
    assert evaluate_point(series, covered, DAY, CONFIG).status == "insufficient_history"


def test_day_without_data_is_not_evaluated() -> None:
    series, covered = build([100.0] * 28, None)
    assert evaluate_point(series, covered, DAY, CONFIG).status == "no_data"


def test_new_spend_uses_absolute_threshold_and_has_no_percentage() -> None:
    series, covered = build([0.0] * 28, 80.0)
    result = evaluate_point(series, covered, DAY, CONFIG)
    assert result.status == "anomaly"
    assert result.kind == "new_spend"
    assert result.deviation_pct is None
    small, covered = build([0.0] * 28, 20.0)
    assert evaluate_point(small, covered, DAY, CONFIG).status == "normal"


def test_scope_missing_on_covered_days_counts_as_zero_cost() -> None:
    # Covered days where this scope had no records are genuine zeros (new spend).
    series = {DAY: Decimal(500)}
    covered = {DAY - timedelta(days=i) for i in range(29)}
    result = evaluate_point(series, covered, DAY, CONFIG)
    assert (result.status, result.kind, result.expected) == ("anomaly", "new_spend", 0)


def test_decreases_and_credits_never_alert() -> None:
    series, covered = build([100.0] * 28, 5.0)
    assert evaluate_point(series, covered, DAY, CONFIG).status == "normal"
    series, covered = build([-50.0] * 28, -10.0)  # credits shrinking is still negative cost
    assert evaluate_point(series, covered, DAY, CONFIG).status == "normal"


def test_negative_baseline_with_positive_cost_is_new_spend() -> None:
    series, covered = build([-5.0] * 28, 120.0)
    result = evaluate_point(series, covered, DAY, CONFIG)
    assert (result.status, result.kind) == ("anomaly", "new_spend")


def test_weekday_pattern_uses_day_of_week_baseline() -> None:
    # Weekends cost 300, weekdays 100. DAY is a Wednesday: 300 is a real spike.
    history = []
    start = DAY - timedelta(days=56)
    for i in range(56):
        history.append(300.0 if (start + timedelta(days=i)).weekday() >= 5 else 100.0)
    series, covered = build(history, 300.0)
    result = evaluate_point(series, covered, DAY, CONFIG)
    assert result.method == "day_of_week_median"
    assert result.expected == Decimal(100)
    assert result.status == "anomaly"
    # The same 300 on a Saturday is normal.
    saturday = DAY + timedelta(days=3)
    series[saturday] = Decimal(300)
    covered.add(saturday)
    for extra in (1, 2):
        series[DAY + timedelta(days=extra)] = Decimal(100)
        covered.add(DAY + timedelta(days=extra))
    assert evaluate_point(series, covered, saturday, CONFIG).status == "normal"


def test_earlier_spike_does_not_distort_median_baseline() -> None:
    history = [100.0] * 28
    history[14] = 5000.0  # DAY - 14: one of the four same-weekday baseline points
    series, covered = build(history, 400.0)
    result = evaluate_point(series, covered, DAY, CONFIG)
    assert result.expected == Decimal(100)
    assert result.status == "anomaly"


@pytest.mark.parametrize(
    ("deviation", "pct", "expected"),
    [
        (Decimal(50), Decimal(400), "low"),  # big % but small amount
        (Decimal(150), Decimal(60), "medium"),
        (Decimal(600), Decimal(150), "high"),
        (Decimal(5000), Decimal(500), "critical"),
        (Decimal(5000), Decimal(40), "low"),  # big amount but small %
        (Decimal(700), None, "high"),  # new spend: amount only
    ],
)
def test_severity_requires_both_percentage_and_amount(deviation, pct, expected) -> None:
    assert classify_severity(CONFIG, deviation, pct) == expected
