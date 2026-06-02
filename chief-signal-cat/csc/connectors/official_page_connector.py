import json
import logging
import time
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from csc.connectors.http import fetch_with_retry, validate_source_config
from csc.schemas.items import RawItem
from csc.utils.text_cleaning import clean_body

logger = logging.getLogger("csc.connectors.official_page")

# ── Selectors / layout constants ──────────────────────────────
# Change here when ASIC updates their page structure.
ASIC_BASE_URL = "https://www.asic.gov.au"
DETAIL_BODY_ID = "nh-article-body"     # <div id="nh-article-body"> on detail pages
DETAIL_FETCH_DELAY = 0.5               # polite delay (seconds) between detail page fetches


# ── Public API ────────────────────────────────────────────────

def fetch_official_page(source_cfg: dict) -> list[RawItem]:
    """
    Fetch ASIC media releases via JSON listing + detail page body text.

    Stage 1: GET the JSON listing from source_cfg["url"], filter to max_items newest.
    Stage 2: For each release, GET the detail page and extract body from DETAIL_BODY_ID.
             Falls back to metaDescription if the detail fetch fails or body is empty.
    """
    validate_source_config(source_cfg)
    max_items = source_cfg.get("max_items", 20)

    raw_json = fetch_with_retry(source_cfg["url"], source_cfg["name"])
    if raw_json is None:
        return []

    try:
        releases = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        logger.error("json parse error", extra={"source": source_cfg["name"], "error": str(exc)})
        return []

    if not releases:
        logger.warning("listing yielded zero items — ASIC may have changed their API",
                       extra={"source": source_cfg["name"]})
        return []

    # JSON is newest-first; cap before fetching detail pages to limit HTTP traffic.
    releases = releases[:max_items]

    now = datetime.now(timezone.utc)
    items: list[RawItem] = []
    for release in releases:
        try:
            item = _fetch_one(release, source_cfg, now)
            if item is not None:
                items.append(item)
        except Exception as exc:
            logger.warning(
                "skipping release",
                extra={"source": source_cfg["name"],
                       "doc": release.get("documentNumber", "?"),
                       "error": str(exc)},
            )
        time.sleep(DETAIL_FETCH_DELAY)

    logger.info("fetched", extra={"source": source_cfg["name"], "count": len(items)})
    return items


# ── Internal helpers ──────────────────────────────────────────

def _fetch_one(release: dict, source_cfg: dict, fetched_at: datetime) -> RawItem | None:
    relative_url = release.get("url")
    if not relative_url:
        return None

    url = ASIC_BASE_URL + relative_url

    html = fetch_with_retry(url, source_cfg["name"])
    if html:
        body = _extract_body(html)
    else:
        body = ""
        logger.warning("detail fetch failed, using fallback",
                       extra={"source": source_cfg["name"], "url": url})

    if not body:
        # metaDescription is plain text; summary is HTML — strip both defensively.
        fallback = release.get("metaDescription") or release.get("summary") or ""
        body = _strip_html(fallback)

    return RawItem(
        id=RawItem.generate_id(url),
        url=url,
        canonical_url=url,
        title=clean_body(release["name"]),
        body=clean_body(body),
        source_name=source_cfg["name"],
        source_type=source_cfg["type"],
        trust_tier=source_cfg["trust_tier"],
        source_weight=float(source_cfg.get("source_weight", 1.0)),
        region=source_cfg["region"],
        published_at=_parse_date(release.get("publishedDate")),
        fetched_at=fetched_at,
        raw_metadata={
            "release_id": release.get("id"),
            "document_number": release.get("documentNumber"),
            "meta_subject": release.get("metaSubject"),
            "meta_function": release.get("metaFunction"),
        },
    )


def _extract_body(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    div = soup.find(id=DETAIL_BODY_ID)
    if div is None:
        return ""
    return div.get_text(separator=" ", strip=True)


def _strip_html(text: str) -> str:
    """Strip HTML tags from a string using BeautifulSoup."""
    return BeautifulSoup(text, "html.parser").get_text(separator=" ", strip=True)


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
