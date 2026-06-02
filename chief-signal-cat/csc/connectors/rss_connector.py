import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from csc.connectors.http import fetch_with_retry as _fetch_with_retry, validate_source_config
from csc.schemas.items import RawItem

logger = logging.getLogger("csc.connectors.rss")


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
