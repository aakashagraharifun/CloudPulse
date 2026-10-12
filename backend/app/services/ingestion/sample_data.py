"""Deterministic synthetic billing data for demos and tests.

THIS IS SYNTHETIC DATA. It is generated, not exported from a real cloud account.

The dataset covers `days` days ending on `end_date`. It mixes cloud
infrastructure (AWS, Google Cloud, Microsoft Azure), AI model APIs (OpenAI,
Anthropic, Google Gemini; billed per token, with a `model`) and a SaaS tool
(Datadog), and contains three deliberately injected anomalies so the detection
and investigation features can be demonstrated:

1. GPU spike (end_date - 4 and end_date - 3): a new p4d.24xlarge EC2 instance
   appears in us-west-2 for the `ml-experiments` project.
2. Data-transfer spike (end_date - 11): NAT Gateway processed bytes jump ~8x on
   untagged networking resources (usage-driven increase, no project tag).
3. LLM token spike (end_date - 6): Claude output tokens for the
   `support-assistant` project jump 10x (usage-driven increase on one model).

Unit prices are illustrative list prices, not quotes.
"""

import csv
import io
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

SAMPLE_COLUMNS = (
    "usage_date",
    "provider",
    "account_id",
    "service",
    "resource_id",
    "region",
    "usage_type",
    "model",
    "usage_quantity",
    "usage_unit",
    "currency",
    "cost",
    "project",
    "environment",
)

PROD_ACCOUNT = "111122223333"
DEV_ACCOUNT = "444455556666"
GCP_PROJECT = "cloudpulse-analytics-prod"
AZURE_SUBSCRIPTION = "8f2c4e1a-5b7d-4c3e-9a6f-2d1b0e7c9a35"
OPENAI_ORG = "org-cloudpulse-demo"
ANTHROPIC_ORG = "cloudpulse-demo"
GEMINI_PROJECT = "cloudpulse-ai-prod"
DATADOG_ORG = "cloudpulse-demo"


@dataclass(frozen=True)
class SampleLine:
    provider: str
    account_id: str
    service: str
    resource_id: str
    region: str
    usage_type: str
    usage_unit: str
    unit_price: Decimal
    daily_quantity: Decimal
    project: str
    environment: str
    weekend_factor: float = 1.0  # multiplier applied on Saturday/Sunday
    noise: float = 0.04  # +/- relative jitter
    model: str = ""


def _d(value: str) -> Decimal:
    return Decimal(value)


EC2 = "Amazon Elastic Compute Cloud"
# fmt: off
LINES: tuple[SampleLine, ...] = (
    # Storefront web tier (production)
    *(
        SampleLine("aws", PROD_ACCOUNT, EC2, f"i-0a4f9c2e7b1d38e5{n}", "us-east-1",
                   "BoxUsage:m6i.2xlarge", "Hrs", _d("0.384"), _d("24"),
                   "storefront", "production", noise=0.0)
        for n in range(1, 4)
    ),
    SampleLine("aws", PROD_ACCOUNT, "Amazon CloudFront", "E2QWRUHAPOMQZL", "global",
               "DataTransfer-Out-Bytes", "GB", _d("0.085"), _d("160"),
               "storefront", "production", weekend_factor=0.7),
    SampleLine("aws", PROD_ACCOUNT, "Amazon Simple Storage Service", "cp-storefront-assets",
               "us-east-1", "TimedStorage-ByteHrs", "GB-Mo", _d("0.023"), _d("390"),
               "storefront", "production", noise=0.01),
    # Payments API (production)
    *(
        SampleLine("aws", PROD_ACCOUNT, EC2, f"i-07c1d5e9a3b2f846{n}", "us-east-1",
                   "BoxUsage:c6i.4xlarge", "Hrs", _d("0.68"), _d("24"),
                   "payments-api", "production", noise=0.0)
        for n in range(1, 3)
    ),
    SampleLine("aws", PROD_ACCOUNT, "Amazon Relational Database Service", "payments-db-prod",
               "us-east-1", "InstanceUsage:db.r6g.2xlarge", "Hrs", _d("0.96"), _d("24"),
               "payments-api", "production", noise=0.0),
    SampleLine("aws", PROD_ACCOUNT, "AWS Lambda", "payments-webhook-handler", "us-east-1",
               "Lambda-GB-Second", "GB-Seconds", _d("0.0000166667"), _d("240000"),
               "payments-api", "production", weekend_factor=0.6, noise=0.08),
    SampleLine("aws", PROD_ACCOUNT, "Amazon Elastic Kubernetes Service", "payments-eks",
               "us-east-1", "AmazonEKS-Hours:perCluster", "Hrs", _d("0.10"), _d("24"),
               "payments-api", "production", noise=0.0),
    # Analytics (production)
    SampleLine("aws", PROD_ACCOUNT, "Amazon DynamoDB", "events-table", "us-east-1",
               "WriteRequestUnits", "WriteRequestUnits", _d("0.00000125"), _d("5600000"),
               "analytics", "production", weekend_factor=0.8, noise=0.06),
    SampleLine("gcp", GCP_PROJECT, "BigQuery", "analytics-warehouse", "US",
               "Analysis", "TiB", _d("6.25"), _d("1.8"),
               "analytics", "production", weekend_factor=0.4, noise=0.1),
    SampleLine("gcp", GCP_PROJECT, "Cloud Storage", "cp-analytics-exports", "US",
               "Standard Storage US Multi-region", "GiB-Mo", _d("0.026"), _d("78"),
               "analytics", "production", noise=0.01),
    # Shared networking and monitoring: intentionally untagged (no project/environment)
    SampleLine("aws", PROD_ACCOUNT, "Amazon Virtual Private Cloud", "nat-0b7e4c1a9d2f35e68",
               "us-east-1", "NatGateway-Bytes", "GB", _d("0.045"), _d("130"), "", "",
               weekend_factor=0.75),
    SampleLine("aws", PROD_ACCOUNT, "Amazon Virtual Private Cloud", "nat-0b7e4c1a9d2f35e68",
               "us-east-1", "NatGateway-Hours", "Hrs", _d("0.045"), _d("24"), "", "", noise=0.0),
    SampleLine("aws", PROD_ACCOUNT, "Amazon CloudWatch", "", "us-east-1",
               "CW:MetricMonitorUsage", "Metrics", _d("0.01"), _d("300"), "", "", noise=0.02),
    # Staging
    SampleLine("aws", DEV_ACCOUNT, EC2, "i-0d2b8f4a6c1e9357b", "us-east-1",
               "BoxUsage:m6i.large", "Hrs", _d("0.096"), _d("24"),
               "storefront", "staging", noise=0.0),
)
# fmt: on

PER_MTOK = Decimal("0.000001")


def _per_mtok(price: str) -> Decimal:
    """Unit price per token from a price per million tokens."""
    return Decimal(price) * PER_MTOK


SONNET = "claude-sonnet-4-5"
# Multi-cloud, AI model API and SaaS lines. They draw jitter from their own random
# generator, so adding them left every value of the lines above unchanged.
# fmt: off
EXTRA_LINES: tuple[SampleLine, ...] = (
    # Microsoft Azure: reporting workloads
    SampleLine("azure", AZURE_SUBSCRIPTION, "Virtual Machines", "vm-reporting-01", "eastus",
               "D4s v5", "Hrs", _d("0.192"), _d("24"), "analytics", "production", noise=0.0),
    SampleLine("azure", AZURE_SUBSCRIPTION, "Storage", "streportingexports", "eastus",
               "Hot LRS Data Stored", "GB-Mo", _d("0.0184"), _d("210"),
               "analytics", "production", noise=0.01),
    # OpenAI: search assistant chat model and document embeddings
    SampleLine("openai", OPENAI_ORG, "OpenAI API", "proj_search_assistant", "global",
               "input_tokens", "tokens", _per_mtok("2.50"), _d("1600000"),
               "search", "production", weekend_factor=0.55, noise=0.08, model="gpt-4o"),
    SampleLine("openai", OPENAI_ORG, "OpenAI API", "proj_search_assistant", "global",
               "output_tokens", "tokens", _per_mtok("10.00"), _d("220000"),
               "search", "production", weekend_factor=0.55, noise=0.08, model="gpt-4o"),
    SampleLine("openai", OPENAI_ORG, "OpenAI API", "proj_doc_indexing", "global",
               "input_tokens", "tokens", _per_mtok("0.02"), _d("40000000"),
               "analytics", "production", weekend_factor=0.3, noise=0.12,
               model="text-embedding-3-small"),
    # Anthropic: customer-support assistant
    SampleLine("anthropic", ANTHROPIC_ORG, "Claude API", "wrkspc_support_assistant", "global",
               "input_tokens", "tokens", _per_mtok("3.00"), _d("1200000"),
               "support-assistant", "production", weekend_factor=0.6, noise=0.07, model=SONNET),
    SampleLine("anthropic", ANTHROPIC_ORG, "Claude API", "wrkspc_support_assistant", "global",
               "output_tokens", "tokens", _per_mtok("15.00"), _d("180000"),
               "support-assistant", "production", weekend_factor=0.6, noise=0.07, model=SONNET),
    # Google Gemini API: ticket classification
    SampleLine("google-ai", GEMINI_PROJECT, "Gemini API", "ticket-classifier", "global",
               "input_tokens", "tokens", _per_mtok("0.30"), _d("3000000"),
               "support-assistant", "production", weekend_factor=0.6, noise=0.08,
               model="gemini-2.5-flash"),
    SampleLine("google-ai", GEMINI_PROJECT, "Gemini API", "ticket-classifier", "global",
               "output_tokens", "tokens", _per_mtok("2.50"), _d("400000"),
               "support-assistant", "production", weekend_factor=0.6, noise=0.08,
               model="gemini-2.5-flash"),
    # Datadog: shared monitoring, intentionally untagged
    SampleLine("datadog", DATADOG_ORG, "Infrastructure Monitoring", "", "global",
               "infra_hosts", "Host-days", _d("0.5"), _d("8"), "", "", noise=0.0),
)
# fmt: on

LLM_SPIKE_DAYS_BEFORE_END = 6
LLM_SPIKE_FACTOR = 10.0  # Claude output tokens on the spike day

GPU_SPIKE = SampleLine(
    "aws", DEV_ACCOUNT, EC2, "i-0f3e9a7c5b1d2468a", "us-west-2",
    "BoxUsage:p4d.24xlarge", "Hrs", _d("32.7726"), _d("24"),
    "ml-experiments", "development", noise=0.0,
)  # fmt: skip
GPU_SPIKE_HOURS = {4: _d("24"), 3: _d("18")}  # days before end_date -> hours running
NAT_SPIKE_DAYS_BEFORE_END = 11
NAT_SPIKE_FACTOR = 8.0
DAILY_GROWTH = 0.002  # +0.2% per day organic growth on variable usage


def _q(value: Decimal, places: str) -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_EVEN)


def default_end_date() -> date:
    return datetime.now(UTC).date() - timedelta(days=1)


def generate_sample_rows(
    end_date: date | None = None, days: int = 90, seed: int = 42
) -> list[dict[str, str]]:
    end_date = end_date or default_end_date()
    rng = random.Random(seed)
    extra_rng = random.Random(seed + 1)
    rows: list[dict[str, str]] = []

    def emit(day: date, line: SampleLine, quantity: Decimal) -> None:
        quantity = _q(quantity, "0.0001")
        rows.append(
            {
                "usage_date": day.isoformat(),
                "provider": line.provider,
                "account_id": line.account_id,
                "service": line.service,
                "resource_id": line.resource_id,
                "region": line.region,
                "usage_type": line.usage_type,
                "model": line.model,
                "usage_quantity": format(quantity, "f"),
                "usage_unit": line.usage_unit,
                "currency": "USD",
                "cost": format(_q(quantity * line.unit_price, "0.000001"), "f"),
                "project": line.project,
                "environment": line.environment,
            }
        )

    for offset in range(days - 1, -1, -1):
        day = end_date - timedelta(days=offset)
        day_index = days - 1 - offset
        weekend = day.weekday() >= 5
        for line in LINES:
            factor = 1.0
            if line.noise:  # only variable usage grows; fixed instances do not
                factor *= (1 + DAILY_GROWTH) ** day_index
                factor *= 1 + rng.uniform(-line.noise, line.noise)
            if weekend:
                factor *= line.weekend_factor
            if line.usage_type == "NatGateway-Bytes" and offset == NAT_SPIKE_DAYS_BEFORE_END:
                factor *= NAT_SPIKE_FACTOR
            emit(day, line, line.daily_quantity * Decimal(str(round(factor, 6))))
        for line in EXTRA_LINES:
            factor = 1.0
            if line.noise:
                factor *= (1 + DAILY_GROWTH) ** day_index
                factor *= 1 + extra_rng.uniform(-line.noise, line.noise)
            if weekend:
                factor *= line.weekend_factor
            if (
                line.model == SONNET
                and line.usage_type == "output_tokens"
                and offset == LLM_SPIKE_DAYS_BEFORE_END
            ):
                factor *= LLM_SPIKE_FACTOR
            emit(day, line, line.daily_quantity * Decimal(str(round(factor, 6))))
        if offset in GPU_SPIKE_HOURS:
            emit(day, GPU_SPIKE, GPU_SPIKE_HOURS[offset])
    return rows


def generate_sample_csv(end_date: date | None = None, days: int = 90, seed: int = 42) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=SAMPLE_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(generate_sample_rows(end_date, days, seed))
    return buffer.getvalue()
