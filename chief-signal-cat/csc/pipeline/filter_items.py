import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from csc.schemas.items import FilteredItem, RawItem

logger = logging.getLogger("csc.pipeline.filter")


def _word_boundary_pattern(keyword: str) -> re.Pattern:
    return re.compile(r"\b" + re.escape(keyword) + r"\b")


def filter_items(items: list[RawItem], cfg: dict) -> list[FilteredItem]:
    """
    Apply deterministic filter chain. No LLM calls.
    Returns all items — kept and dropped — with filter_status and filter_reason set.
    Caller splits on filter_status to decide what to persist vs pass forward.
    """
    target_regions = set(cfg.get("target_regions", ["AU"]))
    max_age_days = cfg.get("max_age_days", 7)
    domain_allowlist = {_normalise_domain(d) for d in cfg.get("domain_allowlist", [])}
    keyword_allowlist_orig = cfg.get("keyword_allowlist", [])
    # Precompile word-boundary patterns — prevents "EV" matching "revenue", "event", etc.
    allowlist_patterns = [
        (orig, _word_boundary_pattern(orig.lower()))
        for orig in keyword_allowlist_orig
    ]
    blocklist_patterns = [
        _word_boundary_pattern(k.lower())
        for k in cfg.get("keyword_blocklist", [])
    ]
    blocklist_orig = [k.lower() for k in cfg.get("keyword_blocklist", [])]
    require_keyword_match = cfg.get("require_keyword_match", False)
    min_keyword_matches = cfg.get("min_keyword_matches", 1)
    exempt_tiers = set(cfg.get("keyword_match_exempt_tiers", []))
    missing_date_policy = cfg.get("missing_published_at_policy", {})
    now = datetime.now(timezone.utc)

    result: list[FilteredItem] = []
    for raw in items:
        text = (raw.title + " " + raw.body).lower()
        matched = [orig for orig, pat in allowlist_patterns if pat.search(text)]

        filter_status, filter_reason = _get_filter_outcome(
            raw,
            target_regions,
            max_age_days,
            domain_allowlist,
            blocklist_patterns,
            require_keyword_match,
            min_keyword_matches,
            exempt_tiers,
            missing_date_policy,
            matched,
            now,
        )

        excluded = (
            [k for k, pat in zip(blocklist_orig, blocklist_patterns) if pat.search(text)]
            if filter_status == "dropped" and filter_reason == "blocked_keyword"
            else []
        )

        fi = FilteredItem(
            **vars(raw),
            filter_status=filter_status,
            filter_reason=filter_reason,
            matched_keywords=matched,
            excluded_keywords=excluded,
        )
        if filter_status == "dropped":
            logger.debug("dropped", extra={"id": raw.id, "reason": filter_reason})
        elif filter_status == "keep_with_warning":
            logger.debug("kept with warning", extra={"id": raw.id, "reason": filter_reason})
        result.append(fi)

    kept = sum(1 for i in result if i.filter_status != "dropped")
    logger.info(
        "filter complete",
        extra={"total": len(items), "kept": kept, "dropped": len(items) - kept},
    )
    return result


def _normalise_domain(domain: str) -> str:
    return domain.lower().removeprefix("www.")


def _get_filter_outcome(
    item: RawItem,
    target_regions: set,
    max_age_days: int,
    domain_allowlist: set,
    blocklist_patterns: list[re.Pattern],
    require_keyword_match: bool,
    min_keyword_matches: int,
    exempt_tiers: set,
    missing_date_policy: dict,
    matched_keywords: list[str],
    now: datetime,
) -> tuple[str, str | None]:
    """Returns (filter_status, filter_reason). filter_status: kept | dropped | keep_with_warning."""

    # 1. Region check
    if item.region not in target_regions:
        return "dropped", "off_region"

    # 2. Recency — missing date sets pending warning but continues through remaining checks
    status = "kept"
    reason = None

    if item.published_at is None:
        policy = missing_date_policy.get(item.trust_tier, missing_date_policy.get(item.source_type, "drop"))
        if policy == "drop":
            return "dropped", "missing_date"
        logger.warning(
            "item has no published_at",
            extra={"id": item.id, "source": item.source_name, "trust_tier": item.trust_tier},
        )
        status, reason = "keep_with_warning", "missing_published_at"
    elif item.published_at < now - timedelta(days=max_age_days):
        return "dropped", "stale"

    # 3. Domain allowlist
    if domain_allowlist:
        domain = _normalise_domain(urlparse(item.url).netloc)
        if domain not in domain_allowlist:
            return "dropped", "blocked_domain"

    # 4. Keyword blocklist
    text = (item.title + " " + item.body).lower()
    if any(pat.search(text) for pat in blocklist_patterns):
        return "dropped", "blocked_keyword"

    # 5. Keyword allowlist (strict mode)
    if require_keyword_match and item.trust_tier not in exempt_tiers:
        if len(matched_keywords) < min_keyword_matches:
            return "dropped", "no_keyword_match"

    return status, reason
