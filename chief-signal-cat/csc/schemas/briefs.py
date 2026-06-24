from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Brief:
    run_id: str
    date_range: str
    generated_at: datetime
    one_line_readout: str
    markdown_body: str
    top_signal_ids: list[str] = field(default_factory=list)
    watch_item: str = ""
    human_review_ids: list[str] = field(default_factory=list)
    # Items held by the verify gate — pulled from the brief into the review queue.
    review_queue_ids: list[str] = field(default_factory=list)
