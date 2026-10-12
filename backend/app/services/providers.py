"""Known cost providers: display names, categories and name normalization.

CloudPulse accepts any provider slug (`^[a-z0-9][a-z0-9_-]{0,31}$`). Providers
listed here get a display name, a category for "cloud vs AI" analysis, and
common spellings ("Microsoft Azure", "Google Cloud Platform") mapped to their
slug at import time. Unknown providers are kept as-is and grouped as "other".
"""

import re
from dataclasses import dataclass

from sqlalchemy import ColumnElement, case, literal

from app.models import BillingRecord


@dataclass(frozen=True)
class ProviderInfo:
    slug: str
    name: str
    category: str  # cloud | ai | saas


CATEGORY_LABELS = {
    "cloud": "Cloud infrastructure",
    "ai": "AI & LLM APIs",
    "saas": "SaaS & data platforms",
    "other": "Other",
}

PROVIDERS: tuple[ProviderInfo, ...] = (
    # Cloud infrastructure
    ProviderInfo("aws", "Amazon Web Services", "cloud"),
    ProviderInfo("gcp", "Google Cloud", "cloud"),
    ProviderInfo("azure", "Microsoft Azure", "cloud"),
    ProviderInfo("oci", "Oracle Cloud", "cloud"),
    ProviderInfo("alibaba", "Alibaba Cloud", "cloud"),
    ProviderInfo("digitalocean", "DigitalOcean", "cloud"),
    ProviderInfo("cloudflare", "Cloudflare", "cloud"),
    # AI model APIs
    ProviderInfo("openai", "OpenAI", "ai"),
    ProviderInfo("anthropic", "Anthropic", "ai"),
    ProviderInfo("google-ai", "Google Gemini API", "ai"),
    ProviderInfo("mistral", "Mistral AI", "ai"),
    ProviderInfo("deepseek", "DeepSeek", "ai"),
    ProviderInfo("huggingface", "Hugging Face", "ai"),
    # SaaS and data platforms
    ProviderInfo("datadog", "Datadog", "saas"),
    ProviderInfo("snowflake", "Snowflake", "saas"),
    ProviderInfo("databricks", "Databricks", "saas"),
    ProviderInfo("mongodb", "MongoDB Atlas", "saas"),
)
PROVIDERS_BY_SLUG = {p.slug: p for p in PROVIDERS}
CATEGORIES = tuple(CATEGORY_LABELS)

# Common spellings found in exports, keyed by the whitespace-collapsed lower-case form.
_ALIASES = {
    "amazon web services": "aws",
    "google cloud": "gcp",
    "google cloud platform": "gcp",
    "microsoft azure": "azure",
    "oracle": "oci",
    "oracle cloud": "oci",
    "oracle cloud infrastructure": "oci",
    "alibaba cloud": "alibaba",
    "aliyun": "alibaba",
    "open ai": "openai",
    "anthropic api": "anthropic",
    "claude": "anthropic",
    "gemini": "google-ai",
    "google gemini": "google-ai",
    "google ai": "google-ai",
    "google ai studio": "google-ai",
    "mistral ai": "mistral",
    "hugging face": "huggingface",
    "mongodb atlas": "mongodb",
}
for _provider in PROVIDERS:
    _ALIASES.setdefault(_provider.name.lower(), _provider.slug)

_WHITESPACE = re.compile(r"\s+")


def normalize_provider(raw: str) -> str:
    """'Microsoft Azure' -> 'azure'; unknown values are only trimmed and lower-cased."""
    value = _WHITESPACE.sub(" ", raw.strip().lower())
    return _ALIASES.get(value, value)


def category_of(provider: str) -> str:
    info = PROVIDERS_BY_SLUG.get(provider)
    return info.category if info else "other"


def providers_in(category: str) -> list[str]:
    return [p.slug for p in PROVIDERS if p.category == category]


def value_label(dimension: str, value: str) -> str:
    """Display form of a provider or category value; other values are returned as-is."""
    if dimension == "provider":
        info = PROVIDERS_BY_SLUG.get(value)
        return info.name if info else value
    if dimension == "category":
        return CATEGORY_LABELS.get(value, value)
    return value


def category_expression() -> ColumnElement[str]:
    """SQL expression mapping billing_records.provider to its category."""
    return case(
        {p.slug: p.category for p in PROVIDERS},
        value=BillingRecord.provider,
        else_=literal("other"),
    )
