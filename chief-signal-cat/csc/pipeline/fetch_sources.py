from csc.connectors.rss_connector import fetch_all_sources as _rss_fetch_all, validate_source_config
from csc.schemas.items import RawItem


def fetch_all_sources(sources_cfg: list[dict]) -> list[RawItem]:
    """
    Entry point for the fetch stage.
    Config validation is fatal (ValueError propagates to run.py).
    Per-source network failures are recoverable (logged, pipeline continues).
    """
    return _rss_fetch_all(sources_cfg)
