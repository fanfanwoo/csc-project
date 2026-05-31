import dataclasses
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from csc.schemas.briefs import Brief
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


def save_brief(brief: Brief) -> Path:
    briefs_dir = _DATA_DIR / "briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)
    md_path = briefs_dir / f"{brief.run_id}.md"
    md_path.write_text(brief.markdown_body)
    meta_path = briefs_dir / f"{brief.run_id}.json"
    meta = asdict(brief)
    del meta["markdown_body"]
    meta_path.write_text(json.dumps(meta, default=_serialise, indent=2))
    return md_path


def append_items(run_id: str, stage: str, items: list) -> None:
    path = _DATA_DIR / stage / f"{run_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        for item in items:
            f.write(json.dumps(asdict(item), default=_serialise) + "\n")
