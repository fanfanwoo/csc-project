import dataclasses
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from csc.schemas.runs import RunLog

_DATA_DIR = Path(__file__).parent.parent.parent / "data"


def _serialise(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"not serialisable: {type(obj)}")


def append_run_log(log: RunLog) -> None:
    path = _DATA_DIR / "logs" / f"{log.run_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(asdict(log), default=_serialise) + "\n")


def append_items(run_id: str, stage: str, items: list) -> None:
    path = _DATA_DIR / stage / f"{run_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        for item in items:
            f.write(json.dumps(asdict(item), default=_serialise) + "\n")
