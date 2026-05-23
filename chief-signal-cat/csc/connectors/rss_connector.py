import logging
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from csc.schemas.items import RawItem, VALID_SOURCE_TYPES, VALID_TRUST_TIERS, VALID_REGIONS

logger = logging.getLogger("csc.connectors.rss")

_REQUIRED_SOURCE_FIELDS = {"name", "type", "trust_tier", "url", "region"}


# ── Public API ────────────────────────────────────────────────

def validate_source_config(source_cfg: dict) -> None:
    """
    Validate a source config dict. Raises ValueError on any invalid field.
    Must be called before any network fetch — config errors are fatal, not recoverable.
    """
    missing = _REQUIRED_SOURCE_FIELDS - set(source_cfg.keys())
    if missing:
        raise ValueError(f"Source '{source_cfg.get('name', '?')}' missing required fields: {missing}")

    name = source_cfg["name"]

    if source_cfg["type"] not in VALID_SOURCE_TYPES:
        raise ValueError(
            f"Source '{name}': invalid type '{source_cfg['type']}'. Valid: {VALID_SOURCE_TYPES}"
        )
    if source_cfg["trust_tier"] not in VALID_TRUST_TIERS:
        raise ValueError(
            f"Source '{name}': invalid trust_tier '{source_cfg['trust_tier']}'. Valid: {VALID_TRUST_TIERS}"
        )
    if source_cfg["region"] not in VALID_REGIONS:
        raise ValueError(
            f"Source '{name}': invalid region '{source_cfg['region']}'. Valid: {VALID_REGIONS}"
        )

    url = source_cfg["url"]
    if not url or not url.startswith(("http://", "https://")):
        raise ValueError(
            f"Source '{name}': url must be non-empty and start with http:// or https://, got '{url}'"
        )

    if "source_weight" in source_cfg:
        sw = source_cfg["source_weight"]
        if not isinstance(sw, (int, float)) or not (0.0 <= float(sw) <= 1.0):
            raise ValueError(
                f"Source '{name}': source_weight must be 0.0–1.0, got '{sw}'"
            )

    if "max_items" in source_cfg:
        mi = source_cfg["max_items"]
        if not isinstance(mi, int) or mi < 1:
            raise ValueError(
                f"Source '{name}': max_items must be a positive integer, got '{mi}'"
            )


def fetch_all_sources(sources_cfg: list[dict]) -> list[RawItem]:
    """
    Validate all source configs, then fetch from each.

    Config errors are fatal (ValueError re-raised — stops the pipeline).
    Network/parse errors are recoverable (logged, pipeline continues with other sources).
    """
    # Validate all configs before any network calls — fail fast
    for source_cfg in sources_cfg:
        validate_source_config(source_cfg)

    all_items: list[RawItem] = []
    for source_cfg in sources_cfg:
        try:
            items = fetch_rss(source_cfg)
            logger.info("fetched", extra={"source": source_cfg["name"], "count": len(items)})
            all_items.extend(items)
        except Exception as exc:
            logger.error(
                "source fetch failed",
                extra={"source": source_cfg.get("name", "unknown"), "error": str(exc)},
                exc_info=True,
            )

    logger.info("fetch complete", extra={"sources": len(sources_cfg), "total_items": len(all_items)})
    return all_items


def fetch_rss(source_cfg: dict) -> list[RawItem]:
    """Fetch and parse a single RSS/Atom source. Returns empty list on network failure."""
    validate_source_config(source_cfg)
    max_items = source_cfg.get("max_items", 50)
    xml_content = _fetch_with_retry(source_cfg["url"], source_cfg["name"])
    if xml_content is None:
        return []

    items = _parse_rss(
        xml_content,
        source_name=source_cfg["name"],
        source_type=source_cfg["type"],
        trust_tier=source_cfg["trust_tier"],
        source_weight=float(source_cfg.get("source_weight", 0.5)),
        region=source_cfg["region"],
    )
    if len(items) > max_items:
        logger.info("capping items", extra={"source": source_cfg["name"], "before": len(items), "max": max_items})
        items = items[:max_items]
    return items


# ── Internal helpers ──────────────────────────────────────────

def _fetch_with_retry(
    url: str,
    source_name: str,
    max_attempts: int = 3,
    base_delay: float = 2.0,
) -> str | None:
    for attempt in range(1, max_attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ChiefSignalCat/1.0"})
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.read().decode("utf-8")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            if attempt < max_attempts:
                delay = base_delay ** attempt
                logger.warning(
                    "fetch attempt failed",
                    extra={"source": source_name, "attempt": attempt, "of": max_attempts, "retry_in": delay},
                )
                time.sleep(delay)
            else:
                logger.error(
                    "all fetch attempts failed",
                    extra={"source": source_name, "url": url, "error": str(exc)},
                )
    return None


def _parse_rss(
    xml_content: str,
    source_name: str,
    source_type: str,
    trust_tier: str,
    source_weight: float,
    region: str,
) -> list[RawItem]:
    now = datetime.now(timezone.utc)
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as exc:
        logger.error("xml parse error", extra={"source": source_name, "error": str(exc)})
        return []

    # RSS 2.0 <item> first, then Atom <entry>
    rss_items = root.findall(".//item")
    if not rss_items:
        atom_ns = "http://www.w3.org/2005/Atom"
        rss_items = root.findall(f".//{{{atom_ns}}}entry")

    items = []
    for rss_item in rss_items:
        try:
            raw_item = _parse_single_rss_item(
                rss_item, source_name, source_type, trust_tier, source_weight, region, now
            )
            if raw_item is not None:
                items.append(raw_item)
        except Exception as exc:
            logger.warning("skipping malformed item", extra={"source": source_name, "error": str(exc)})
    return items


def _parse_single_rss_item(
    element: ET.Element,
    source_name: str,
    source_type: str,
    trust_tier: str,
    source_weight: float,
    region: str,
    fetched_at: datetime,
) -> RawItem | None:
    title = _get_text(element, "title") or ""
    link = _get_text(element, "link") or ""
    description = _get_text(element, "description") or ""
    pub_date_str = _get_text(element, "pubDate") or ""

    # Atom fallbacks
    if not link:
        link_el = element.find("{http://www.w3.org/2005/Atom}link")
        if link_el is not None:
            link = link_el.get("href", "")
    if not title:
        title = _get_text(element, "{http://www.w3.org/2005/Atom}title") or ""
    if not description:
        description = _get_text(element, "{http://www.w3.org/2005/Atom}summary") or ""
    if not pub_date_str:
        pub_date_str = _get_text(element, "{http://www.w3.org/2005/Atom}updated") or ""

    if not link:
        logger.debug("skipping item with no link", extra={"source": source_name, "title": title[:50]})
        return None

    # Publisher provenance from RSS <source> element (present in Google News feeds)
    source_el = element.find("source")
    publisher_name = source_el.text.strip() if (source_el is not None and source_el.text) else None
    publisher_url = source_el.get("url") if source_el is not None else None

    # Aggregators wrap URLs in redirects — don't claim the feed link is canonical
    canonical_url = None if trust_tier == "aggregator" else link

    return RawItem(
        id=RawItem.generate_id(link),
        url=link,
        canonical_url=canonical_url,
        title=title.strip(),
        body=_strip_html(description),
        source_name=source_name,
        source_type=source_type,
        trust_tier=trust_tier,
        source_weight=source_weight,
        region=region,
        published_at=_parse_date(pub_date_str),
        fetched_at=fetched_at,
        raw_metadata={
            "raw_pub_date": pub_date_str,
            "publisher_name": publisher_name,
            "publisher_url": publisher_url,
            "aggregator_name": source_name if trust_tier == "aggregator" else None,
        },
    )


def _get_text(element: ET.Element, tag: str) -> str | None:
    child = element.find(tag)
    if child is not None and child.text:
        return child.text
    return None


def _parse_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except (ValueError, TypeError):
        pass
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        pass
    logger.debug("could not parse date", extra={"raw": date_str})
    return None


def _strip_html(text: str) -> str:
    clean = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", clean).strip()
