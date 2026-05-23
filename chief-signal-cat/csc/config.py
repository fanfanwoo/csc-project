import os
from pathlib import Path

import yaml

_CONFIG_DIR = Path(__file__).parent.parent / "config"


def _load(filename: str) -> dict:
    with open(_CONFIG_DIR / filename) as f:
        return yaml.safe_load(f)


def load_config() -> dict:
    cfg = {}
    cfg.update(_load("sources.yaml"))
    cfg.update(_load("filters.yaml"))
    cfg.update(_load("scoring.yaml"))
    cfg.update(_load("email.yaml"))
    return cfg
