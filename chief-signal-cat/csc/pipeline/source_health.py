"""
Source health — did each configured source actually deliver fresh items?

The pipeline is resilient by design: a source that 404s, returns an empty feed,
or quietly freezes is logged and skipped, and the brief is still built from
whatever else arrived. That resilience hides decay — a feed can stop producing
for a week and the brief still reads as a normal brief. ASIC's old
newsroom-all.json endpoint was exactly this: a frozen copy whose every item was
dropped as stale, invisible until someone went looking.

So health is judged per *configured* source, not per source that returned data:
a source missing from the fetched items is the loudest signal there is, and it
has no items to carry the news. Each source gets its own staleness threshold in
sources.yaml (`max_staleness_days`) because their natural cadences differ — a
quiet regulator week is normal, a quiet aggregator day is not.

Freshness is measured in elapsed time, so it does not depend on any timezone.
Only the date *label* does; `tz` chooses the calendar it renders in (UTC by
default) and nothing else.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo

from csc.schemas.items import RawItem
from csc.utils.logging import get_logger

logger = get_logger(__name__)

OK = "ok"
WARNING = "warning"


@dataclass
class SourceHealth:
    """One configured source's delivery state for this run."""

    source_name: str
    status: str                              # OK | WARNING
    item_count: int = 0
    newest_published_at: datetime | None = None
    newest_item_date: str = ""               # ISO date in the report tz; "" when unknown
    age_days: float | None = None            # elapsed days since the newest item
    threshold_days: int | None = None        # from sources.yaml; None = unset
    reason: str = ""                         # why it warns; "" when OK

    @property
    def is_warning(self) -> bool:
        return self.status == WARNING


def assess_sources(
    items: list[RawItem],
    sources_cfg: list[dict],
    tz: tzinfo = timezone.utc,
    now: datetime | None = None,
) -> list[SourceHealth]:
    """Health for every configured source, in config order.

    A source warns when it returned nothing, when its newest item is older than
    its own `max_staleness_days`, or when nothing it returned carries a date (an
    undated feed cannot be shown to be fresh). Each warning is logged at ERROR:
    silent decay is the failure this stage exists to catch.
    """
    now = now or datetime.now(timezone.utc)
    by_source: dict[str, list[RawItem]] = {}
    for item in items:
        by_source.setdefault(item.source_name, []).append(item)

    report = []
    for source_cfg in sources_cfg:
        name = source_cfg.get("name", "unknown")
        health = _assess_one(name, by_source.get(name, []), source_cfg, tz, now)
        if health.is_warning:
            logger.error(
                "source health warning",
                extra={
                    "source": name,
                    "reason": health.reason,
                    "item_count": health.item_count,
                    "newest_item_date": health.newest_item_date or None,
                    "age_days": health.age_days,
                    "threshold_days": health.threshold_days,
                },
            )
        report.append(health)
    return report


def _assess_one(
    name: str,
    items: list[RawItem],
    source_cfg: dict,
    tz: tzinfo,
    now: datetime,
) -> SourceHealth:
    threshold = source_cfg.get("max_staleness_days")

    if not items:
        return SourceHealth(
            source_name=name,
            status=WARNING,
            threshold_days=threshold,
            reason="returned no items",
        )

    dated = [i for i in items if i.published_at is not None]
    if not dated:
        return SourceHealth(
            source_name=name,
            status=WARNING,
            item_count=len(items),
            threshold_days=threshold,
            reason=f"{len(items)} item(s), none carrying a publish date",
        )

    newest = max(_as_utc(i.published_at) for i in dated)
    age_days = (now - newest) / timedelta(days=1)
    health = SourceHealth(
        source_name=name,
        status=OK,
        item_count=len(items),
        newest_published_at=newest,
        newest_item_date=newest.astimezone(tz).strftime("%Y-%m-%d"),
        age_days=round(age_days, 1),
        threshold_days=threshold,
    )

    if threshold is None:
        # Staleness is unjudgeable without a threshold, but silence would read as
        # health. Say so once, here, rather than inventing a default cadence.
        logger.warning("no max_staleness_days configured; staleness unchecked", extra={"source": name})
        return health

    if age_days > threshold:
        health.status = WARNING
        health.reason = f"older than its {threshold}d threshold"
    return health


def _as_utc(ts: datetime) -> datetime:
    """Feed dates are usually offset-aware; a bare one is read as UTC."""
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def render_source_health(report: list[SourceHealth]) -> str:
    """The brief's Source health section: every source, its newest item date, warnings.

    Every source gets a line whether it warns or not — a source that vanished is
    the one a reader most needs to see named.
    """
    warnings = sum(1 for h in report if h.is_warning)
    headline = (
        "all sources fresh" if not warnings else f"{warnings} of {len(report)} source(s) warning"
    )
    lines = [
        "## Source health",
        f"{headline} — newest item per configured source.",
        "",
    ]
    for h in report:
        name = f"**{h.source_name}**" if h.is_warning else h.source_name
        if h.newest_item_date:
            detail = f"newest {h.newest_item_date} ({h.age_days}d old, {h.item_count} item(s))"
        elif h.item_count:
            detail = f"no dated items ({h.item_count} item(s))"
        else:
            detail = "no items"
        verdict = f"WARNING: {h.reason}" if h.is_warning else "OK"
        lines.append(f"- {name} — {detail} — {verdict}")
    return "\n".join(lines)
