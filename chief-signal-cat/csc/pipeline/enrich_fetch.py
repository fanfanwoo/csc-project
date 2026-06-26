"""
Enrich stage — fetch publisher article bodies. Runs after dedup, before evidence_state.

Deterministic: one fetch + parse + fallback per item along a fully pre-enumerable
path — no next-step decisions, so this is a module, not an agent. Reuses
connectors.http.fetch_with_retry (fixed backoff on one URL).

Per-item policy keys on the three-bucket evidence_category (never trust_tier directly).
Because evidence_state runs AFTER this stage, evidence_category is not set on the item
yet — derive it here from trust_tier via the shared helper:

  official   → no-op (ASIC two-stage fetch already populated the body)
  publisher  → fetch canonical_url, extract body
  aggregator → skip (the redirect URL is not fetchable)

This stage owns enrichment_status / enrichment_reason; evidence_state owns the
evidence_* labels and reads the body length this stage produced.
"""

import time

from bs4 import BeautifulSoup

from csc.connectors.http import fetch_with_retry
from csc.schemas.items import FilteredItem
from csc.utils.evidence import category_for
from csc.utils.logging import get_logger
from csc.utils.text_cleaning import clean_body

logger = get_logger(__name__)


def enrich(items: list[FilteredItem], cfg: dict, sources: list[dict]) -> list[FilteredItem]:
    """Fetch and populate article bodies for publisher items in place.

    `sources` supplies the per-source body_selector, looked up by source_name.
    """
    fetch_delay = cfg.get("fetch_delay", 0.5)
    selectors = {s["name"]: s.get("body_selector") for s in sources}

    attempted = success = failed = 0
    for item in items:
        if category_for(item.trust_tier) != "publisher":
            continue  # official already has a body; aggregator URLs are not fetchable
        attempted += 1
        if _enrich_one(item, selectors.get(item.source_name)):
            success += 1
        else:
            failed += 1
        time.sleep(fetch_delay)

    logger.info(
        "enrich complete",
        extra={"attempted": attempted, "success": success, "failed": failed},
    )
    return items


def _enrich_one(item: FilteredItem, selector: str | None) -> bool:
    url = item.canonical_url
    if not url:
        item.enrichment_status = "failed"
        item.enrichment_reason = "no_canonical_url"
        return False

    html = fetch_with_retry(url, item.source_name)
    if html is None:
        item.enrichment_status = "failed"
        item.enrichment_reason = "fetch_failed"
        return False

    body = _extract_body(html, selector)
    if body:
        item.body = clean_body(body)
        item.enrichment_status = "success"
        item.enrichment_reason = "body_found"
        return True

    # Fetched but empty after all fallbacks — paywall or unparseable layout.
    item.enrichment_status = "failed"
    item.enrichment_reason = "paywalled_or_empty"
    return False


def _extract_body(html: str, selector: str | None) -> str:
    """Extract article body text. Order: configured selector → <article> <p> text →
    og:description meta. Returns "" if nothing usable is found."""
    soup = BeautifulSoup(html, "html.parser")

    if selector:
        el = soup.select_one(selector)
        if el:
            txt = _paragraphs(el)
            if txt:
                return txt

    article = soup.find("article")
    if article:
        txt = _paragraphs(article)
        if txt:
            return txt

    og = soup.find("meta", attrs={"property": "og:description"})
    if og and og.get("content", "").strip():
        return og["content"]

    return ""


def _paragraphs(element) -> str:
    return " ".join(p.get_text(" ", strip=True) for p in element.find_all("p")).strip()
