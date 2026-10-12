"""The canonical CloudPulse billing schema and the CSV header aliases it accepts.

Every uploaded file is mapped onto these fields. Header names are matched after
normalization (lower-case, any run of non-alphanumeric characters becomes "_"),
so `lineItem/UnblendedCost`, `Unblended Cost` and `unblended_cost` all match.
When several columns match one field, the alias listed first wins and the
other columns are preserved as extra attributes.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FieldSpec:
    name: str
    required: bool
    description: str
    example: str
    aliases: tuple[str, ...]
    max_length: int | None = None


CANONICAL_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "usage_date",
        True,
        "Day the cost was incurred. ISO 8601 date or timestamp; timestamps are "
        "converted to their UTC calendar date, naive timestamps are treated as UTC.",
        "2026-09-14",
        (
            "usage_date",
            "date",
            "usage_start_date",
            "billing_date",
            "lineitem_usagestartdate",
            "line_item_usage_start_date",
        ),
    ),
    FieldSpec(
        "provider",
        True,
        "Cloud provider identifier (lower-case letters, digits, '-' or '_'). "
        "Optional for AWS Cost and Usage Report files, which default to 'aws'.",
        "aws",
        ("provider", "cloud_provider", "cloud"),
        32,
    ),
    FieldSpec(
        "account_id",
        False,
        "Billing account, subscription or project identifier.",
        "123456789012",
        (
            "account_id",
            "account",
            "linked_account_id",
            "subscription_id",
            "lineitem_usageaccountid",
            "line_item_usage_account_id",
        ),
        128,
    ),
    FieldSpec(
        "service",
        True,
        "Cloud service that produced the cost.",
        "Amazon Elastic Compute Cloud",
        (
            "service",
            "service_name",
            "product_productname",
            "product_product_name",
            "product",
            "lineitem_productcode",
            "line_item_product_code",
        ),
        255,
    ),
    FieldSpec(
        "resource_id",
        False,
        "Identifier of the individual resource.",
        "i-0a1b2c3d4e5f60718",
        ("resource_id", "resource", "lineitem_resourceid", "line_item_resource_id"),
        512,
    ),
    FieldSpec(
        "region",
        False,
        "Region or location of the resource.",
        "us-east-1",
        ("region", "location", "product_region", "product_regioncode", "product_region_code"),
        64,
    ),
    FieldSpec(
        "usage_type",
        False,
        "Provider usage type / SKU description.",
        "BoxUsage:m6i.xlarge",
        ("usage_type", "lineitem_usagetype", "line_item_usage_type", "sku"),
        255,
    ),
    FieldSpec(
        "usage_quantity",
        False,
        "Amount of usage (non-negative number).",
        "24",
        (
            "usage_quantity",
            "quantity",
            "usage_amount",
            "lineitem_usageamount",
            "line_item_usage_amount",
        ),
    ),
    FieldSpec(
        "usage_unit",
        False,
        "Unit of usage_quantity.",
        "Hrs",
        ("usage_unit", "unit", "pricing_unit"),
        64,
    ),
    FieldSpec(
        "currency",
        True,
        "ISO 4217 currency code. Costs in different currencies are never summed together.",
        "USD",
        ("currency", "currency_code", "lineitem_currencycode", "line_item_currency_code"),
    ),
    FieldSpec(
        "cost",
        True,
        "Cost amount using '.' as decimal separator, no thousands separators or "
        "currency symbols. Negative values (credits, refunds) are allowed.",
        "38.42",
        (
            "cost",
            "amount",
            "unblended_cost",
            "lineitem_unblendedcost",
            "line_item_unblended_cost",
        ),
    ),
    FieldSpec(
        "project",
        False,
        "Project / team tag. Untagged costs can be attributed with allocation rules.",
        "storefront",
        (
            "project",
            "tag_project",
            "resourcetags_user_project",
            "resource_tags_user_project",
        ),
        128,
    ),
    FieldSpec(
        "environment",
        False,
        "Environment tag, e.g. production or staging.",
        "production",
        (
            "environment",
            "env",
            "tag_environment",
            "resourcetags_user_environment",
            "resource_tags_user_environment",
        ),
        128,
    ),
)

FIELDS_BY_NAME = {spec.name: spec for spec in CANONICAL_FIELDS}

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_header(raw: str) -> str:
    """`lineItem/UsageStartDate` -> `lineitem_usagestartdate`."""
    return _NON_ALNUM.sub("_", raw.strip().lstrip("﻿").lower()).strip("_")
