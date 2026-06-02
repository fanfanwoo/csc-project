import logging

from csc.connectors.http import validate_source_config
from csc.connectors.rss_connector import fetch_rss
from csc.connectors.official_page_connector import fetch_official_page
from csc.schemas.items import RawItem

logger = logging.getLogger("csc.pipeline.fetch_sources")


def fetch_all_sources(sources_cfg: list[dict]) -> list[RawItem]:
    """
    Validate all source configs (fatal on error), then fetch each source.
    Dispatches to the connector named by source_cfg["connector"] (default: "rss").
    Per-source network failures are recoverable — logged, pipeline continues.
    """
    for source_cfg in sources_cfg:
        validate_source_config(source_cfg)

    all_items: list[RawItem] = []
    for source_cfg in sources_cfg:
        connector_key = source_cfg.get("connector", "rss")
        if connector_key == "rss":
            connector_fn = fetch_rss
        elif connector_key == "official_page":
            connector_fn = fetch_official_page
        else:
            logger.error("unknown connector", extra={"source": source_cfg.get("name"), "connector": connector_key})
            continue
        try:
            items = connector_fn(source_cfg)
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
