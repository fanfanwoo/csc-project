import logging
import ssl
import time
import urllib.error
import urllib.request

import certifi

from csc.schemas.items import VALID_SOURCE_TYPES, VALID_TRUST_TIERS, VALID_REGIONS

_SSL_CTX = ssl.create_default_context(cafile=certifi.where())
_USER_AGENT = "ChiefSignalCat/1.0"

logger = logging.getLogger("csc.connectors.http")

_REQUIRED_SOURCE_FIELDS = {"name", "type", "trust_tier", "url", "region"}


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


def fetch_with_retry(
    url: str,
    source_name: str,
    max_attempts: int = 3,
    base_delay: float = 2.0,
) -> str | None:
    for attempt in range(1, max_attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, context=_SSL_CTX, timeout=30) as response:
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
