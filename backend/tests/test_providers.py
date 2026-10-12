"""Provider registry: slugs, categories and display labels (no database)."""

from app.services.anomaly_detection.service import scope_label
from app.services.providers import (
    CATEGORIES,
    PROVIDERS,
    category_of,
    normalize_provider,
    providers_in,
    value_label,
)


def test_registry_slugs_are_valid_and_unique() -> None:
    slugs = [p.slug for p in PROVIDERS]
    assert len(slugs) == len(set(slugs))
    assert all(normalize_provider(slug) == slug for slug in slugs)
    assert all(p.category in CATEGORIES for p in PROVIDERS)


def test_display_names_map_back_to_their_slug() -> None:
    for provider in PROVIDERS:
        assert normalize_provider(provider.name.upper()) == provider.slug


def test_categories() -> None:
    assert category_of("aws") == "cloud"
    assert category_of("anthropic") == "ai"
    assert category_of("datadog") == "saas"
    assert category_of("acme-cdn") == "other"
    assert {"openai", "anthropic", "google-ai"} <= set(providers_in("ai"))


def test_labels() -> None:
    assert value_label("provider", "azure") == "Microsoft Azure"
    assert value_label("provider", "acme-cdn") == "acme-cdn"
    assert value_label("category", "ai") == "AI & LLM APIs"
    assert value_label("service", "ai") == "ai"
    assert scope_label("provider", "openai") == "Provider: OpenAI"
    assert scope_label("category", "ai") == "Category: AI & LLM APIs"
    assert scope_label("model", "gpt-4o") == "Model: gpt-4o"
