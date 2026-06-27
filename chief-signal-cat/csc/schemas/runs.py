from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class RunLog:
    run_id: str
    started_at: datetime
    status: str  # started | completed | failed
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    items_fetched: int = 0
    items_filtered: int = 0
    items_deduplicated: int = 0
    items_classified: int = 0
    items_held: int = 0
    items_scored: int = 0
    error_count: int = 0
    errors: list[dict] = field(default_factory=list)
    # Operational metrics for watching v1b behaviour across runs (see
    # csc/pipeline/run_metrics.py). Kept as a dict so it can grow without bloating
    # the flat core counts above.
    metrics: dict = field(default_factory=dict)
