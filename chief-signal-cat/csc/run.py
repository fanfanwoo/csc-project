import uuid
from datetime import datetime

from csc.config import load_config
from csc.pipeline.fetch_sources import fetch_all_sources
from csc.pipeline.filter_items import filter_items
from csc.pipeline.deduplicate import deduplicate
from csc.pipeline.classify import classify_items
from csc.pipeline.score import score_items
from csc.pipeline.summarise import summarise
from csc.pipeline.send_email import send_email
from csc.schemas.runs import RunLog
from csc.storage.jsonl_store import append_run_log
from csc.utils.logging import get_logger

logger = get_logger(__name__)


def run_pipeline() -> RunLog:
    run_id = str(uuid.uuid4())
    started_at = datetime.utcnow()
    log = RunLog(run_id=run_id, started_at=started_at, status="started")
    logger.info("pipeline started", extra={"run_id": run_id})

    try:
        cfg = load_config()

        raw = fetch_all_sources(cfg["sources"])
        log.items_fetched = len(raw)

        filtered = filter_items(raw, cfg["filter_rules"])
        log.items_filtered = len(filtered)

        deduped = deduplicate(filtered, cfg["dedup"])
        log.items_deduplicated = len(deduped)

        classified = classify_items(deduped, cfg["classifier"])
        log.items_classified = len(classified)

        scored = score_items(classified, cfg["scorer"])
        log.items_scored = len(scored)

        brief = summarise(scored, cfg["summariser"])
        send_email(brief, cfg["email"])

        log.status = "completed"
    except Exception as exc:
        log.status = "failed"
        log.errors.append({"error": str(exc)})
        logger.exception("pipeline failed", extra={"run_id": run_id})
        raise
    finally:
        log.completed_at = datetime.utcnow()
        log.duration_seconds = (log.completed_at - started_at).total_seconds()
        append_run_log(log)

    return log


if __name__ == "__main__":
    run_pipeline()
