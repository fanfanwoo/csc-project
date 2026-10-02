"""
Validate the real config/*.yaml — not fixtures.

Every other test builds its own config dicts, so a typo in the shipped YAML
reaches the 07:00 run unopposed: broken syntax or a bad value only surfaces as
a failed pipeline, and (for broken syntax) without even an alert email, since
_send_alert needs load_config to read the alert address. These tests make the
shipped files fail the suite instead.

Read-only: parses the files, asserts nothing about the network.
"""

import pytest

from csc.config import load_config
from csc.connectors.http import validate_source_config

VALID_CONNECTORS = {"rss", "official_page", "manual_csv"}


@pytest.fixture(scope="module")
def cfg() -> dict:
    """The real config tree. A YAML syntax error fails here, before any assertion."""
    return load_config()


def test_real_config_parses(cfg):
    for key in ("sources", "pipeline", "filter", "summary", "email"):
        assert key in cfg, f"config/*.yaml is missing the '{key}' block"


def test_every_real_source_passes_validation(cfg):
    """The same validation the pipeline runs before its first fetch."""
    assert cfg["sources"], "no sources configured"
    for source in cfg["sources"]:
        validate_source_config(source)


def test_every_real_source_has_a_staleness_threshold(cfg):
    """Without one, that source is never judged stale — only for returning nothing.

    Not asserting the values: thresholds are tuning, and tuning belongs in the
    config file, not pinned here. Presence is the contract.
    """
    missing = [s["name"] for s in cfg["sources"] if "max_staleness_days" not in s]
    assert not missing, f"sources without max_staleness_days: {missing}"


def test_every_real_source_names_a_known_connector(cfg):
    for source in cfg["sources"]:
        connector = source.get("connector", "rss")
        assert connector in VALID_CONNECTORS, (
            f"source '{source['name']}' names connector '{connector}', "
            f"which fetch_all_sources would skip"
        )


def test_source_names_are_unique(cfg):
    """Health, filters and per-source overrides all key on the name."""
    names = [s["name"] for s in cfg["sources"]]
    assert len(names) == len(set(names)), f"duplicate source names: {names}"


def test_email_config_has_the_addresses_the_pipeline_sends_to(cfg):
    email = cfg["email"]
    assert email.get("recipients"), "email.recipients is empty — the brief would go nowhere"
    assert email.get("alert_address"), "email.alert_address is empty — failures would be silent"
