"""Unit tests for CSV parsing, validation and normalization (no database)."""

from datetime import date
from decimal import Decimal

import pytest

from app.services.normalization.normalizer import (
    FileValidationError,
    normalize_csv,
    parse_decimal,
    parse_usage_date,
)
from app.services.normalization.schema import normalize_header

TODAY = date(2026, 10, 12)
HEADER = "usage_date,provider,service,currency,cost"


def run(text: str, **kwargs):
    return normalize_csv(
        text.encode("utf-8"), max_rows=kwargs.get("max_rows", 1000), max_errors=50, today=TODAY
    )


def test_valid_minimal_file_is_normalized() -> None:
    result = run(f"{HEADER}\n2026-10-01,AWS,Amazon EC2, usd ,12.5\n")
    assert result.is_valid
    assert result.detected_format == "cloudpulse"
    [record] = result.records
    assert record.usage_date == date(2026, 10, 1)
    assert record.provider == "aws"
    assert record.currency == "USD"
    assert record.cost == Decimal("12.50000000")
    assert record.resource_id is None and record.project_tag is None
    assert record.source_row_number == 2


def test_header_aliases_and_case_are_matched() -> None:
    text = (
        "Date,Cloud Provider,Service Name,Currency Code,Unblended Cost,Resource,Location\n"
        "2026-10-01,gcp,BigQuery,USD,3.2,warehouse,US\n"
    )
    [record] = run(text).records
    assert (record.provider, record.service, record.resource_id, record.region) == (
        "gcp",
        "BigQuery",
        "warehouse",
        "US",
    )


def test_aws_cur_headers_default_provider_to_aws_and_keep_extras() -> None:
    text = (
        "lineItem/UsageStartDate,lineItem/ProductCode,lineItem/UnblendedCost,"
        "lineItem/CurrencyCode,resourceTags/user:project,bill/PayerAccountId\n"
        "2026-10-01T23:30:00-05:00,AmazonEC2,1.25,USD,storefront,999\n"
    )
    result = run(text)
    assert result.detected_format == "aws_cur"
    [record] = result.records
    assert record.provider == "aws"
    assert record.service == "AmazonEC2"
    assert record.project_tag == "storefront"
    # 23:30 at UTC-5 is 04:30 UTC the next day.
    assert record.usage_date == date(2026, 10, 2)
    assert record.extra_attributes == {"bill/PayerAccountId": "999"}


def test_missing_required_columns_rejects_file_with_accepted_names() -> None:
    with pytest.raises(FileValidationError, match="Missing required column") as exc:
        run("usage_date,provider,service\n2026-10-01,aws,EC2\n")
    assert "cost (accepted: cost, amount" in str(exc.value)
    assert "currency" in str(exc.value)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"", "empty"),
        (b"   \n", "empty"),
        ("usage_date\n".encode("utf-16"), "UTF-16"),
        (b"usage_date,cost\n\xff\xfe\xfa,1\n", "not valid UTF-8"),
        (f"{HEADER}\n".encode(), "no data rows"),
        (b"usage_date,provider,service,currency,cost,Cost\n", "Duplicate column"),
        (b"usage_date,,service,currency,cost\n", "empty header"),
        (b'usage_date,provider,service,currency,cost\n2026-10-01,aws,"EC2,USD,1\n', "CSV syntax"),
    ],
)
def test_file_level_problems_raise(content: bytes, message: str) -> None:
    with pytest.raises(FileValidationError, match=message):
        normalize_csv(content, max_rows=10, max_errors=10, today=TODAY)


def test_row_limit_is_enforced() -> None:
    rows = "".join(f"2026-10-01,aws,EC2,USD,{i}\n" for i in range(3))
    with pytest.raises(FileValidationError, match="more than 2"):
        run(f"{HEADER}\n{rows}", max_rows=2)


def test_invalid_rows_are_reported_with_line_and_column_and_nothing_is_kept() -> None:
    text = (
        f"{HEADER}\n"
        "2026-10-01,aws,EC2,USD,10\n"  # line 2: valid
        "01/10/2026,aws,EC2,USD,10\n"  # line 3: ambiguous date format
        "2026-10-02,AWS Cloud,EC2,usd1,1,234.00\n"  # line 4: wrong column count
        "2026-10-03,aws,,USD,abc\n"  # line 5: missing service, bad cost
        "2027-01-01,aws,EC2,USD,1\n"  # line 6: future date
    )
    result = run(text)
    assert not result.is_valid
    assert result.records == []
    assert result.rows_total == 5
    assert result.invalid_row_count == 4
    found = {(e.line, e.column) for e in result.errors}
    assert (3, "usage_date") in found
    assert (4, None) in found
    assert (5, "service") in found and (5, "cost") in found
    assert (6, "usage_date") in found


def test_blank_lines_are_skipped_but_line_numbers_stay_physical() -> None:
    result = run(f"{HEADER}\n\n2026-10-01,aws,EC2,USD,x\n")
    assert result.errors[0].line == 3


def test_identical_rows_get_distinct_but_reproducible_fingerprints() -> None:
    text = f"{HEADER}\n2026-10-01,aws,EC2,USD,1\n2026-10-01,aws,EC2,USD,1\n"
    first = [r.fingerprint for r in run(text).records]
    second = [r.fingerprint for r in run(text).records]
    assert len(set(first)) == 2
    assert first == second


def test_fingerprint_ignores_formatting_differences() -> None:
    a = run(f"{HEADER}\n2026-10-01,aws,EC2,USD,1.5\n").records[0].fingerprint
    b = run(f"{HEADER}\n2026-10-01T00:00:00Z,AWS,EC2,usd,1.50000\n").records[0].fingerprint
    assert a == b


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12", Decimal("12")),
        ("-3.5", Decimal("-3.5")),  # credits are allowed
        ("1e2", Decimal("100")),
        (".5", Decimal("0.5")),
        ("0.123456789", Decimal("0.12345679")),  # rounded to 8 places
        ("-0", Decimal("0")),
    ],
)
def test_parse_decimal_valid(raw: str, expected: Decimal) -> None:
    assert parse_decimal(raw, max_abs=Decimal("1e9"), allow_negative=True) == expected


@pytest.mark.parametrize("raw", ["1,000.00", "$5", "NaN", "inf", "1e10", "abc", "1.2.3"])
def test_parse_decimal_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_decimal(raw, max_abs=Decimal("1e9"), allow_negative=True)


def test_parse_decimal_rejects_negative_when_not_allowed() -> None:
    with pytest.raises(ValueError, match="negative"):
        parse_decimal("-1", max_abs=Decimal("1e9"), allow_negative=False)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-02-28", date(2026, 2, 28)),
        ("2026-02-28T23:59:59Z", date(2026, 2, 28)),
        ("2026-02-28T22:00:00-03:00", date(2026, 3, 1)),  # crosses the UTC day boundary
        ("2026-03-01T01:00:00+02:00", date(2026, 2, 28)),
        ("2026-02-28 10:00:00", date(2026, 2, 28)),  # naive -> treated as UTC
    ],
)
def test_parse_usage_date_timezone_boundaries(raw: str, expected: date) -> None:
    assert parse_usage_date(raw, TODAY) == expected


@pytest.mark.parametrize("raw", ["2026-02-30", "2026-13-01", "26-01-01", "2026-01", "1999-12-31"])
def test_parse_usage_date_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_usage_date(raw, TODAY)


def test_normalize_header() -> None:
    assert normalize_header("lineItem/UsageStartDate") == "lineitem_usagestartdate"
    assert normalize_header("﻿ Usage Date ") == "usage_date"
    assert normalize_header("resourceTags/user:project") == "resourcetags_user_project"
