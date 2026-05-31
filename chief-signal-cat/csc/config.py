import os
from pathlib import Path

import yaml

_CONFIG_DIR = Path(__file__).parent.parent / "config"
_ENV_FILE = Path(__file__).parent.parent / ".env"


def _load_dotenv() -> None:
    if not _ENV_FILE.exists():
        return
    with open(_ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()


def _load(filename: str) -> dict:
    with open(_CONFIG_DIR / filename) as f:
        return yaml.safe_load(f)


def load_config() -> dict:
    cfg = {}
    cfg.update(_load("sources.yaml"))
    cfg.update(_load("pipeline.yaml"))
    cfg.update(_load("email.yaml"))
    return cfg
