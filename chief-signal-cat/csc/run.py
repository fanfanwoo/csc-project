import uuid
from datetime import datetime

from csc.config import load_config
from csc.pipeline.fetch_sources import fetch_all_sources
from csc.pipeline.filter_items import filter_items
from csc.pipeline.deduplicate import deduplicate
from csc.pipeline.enrich_fetch import enrich
from csc.pipeline.evidence_state import label_evidence
from csc.pipeline.classify import classify_items
from csc.pipeline.verify import verify_items
from csc.pipeline import run_metrics
from csc.pipeline.score import score_items
from csc.pipeline.summarise import summarise
from csc.pipeline.send_email import send_email
from csc.schemas.runs import RunLog
from csc.storage.jsonl_store import append_items, append_run_log, save_brief
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

        filtered_all = filter_items(raw, cfg["filter"])
        filtered = [i for i in filtered_all if i.filter_status != "dropped"]
        log.items_filtered = len(filtered)

        dedup_stats: dict = {}
        deduped = deduplicate(filtered, cfg["deduplicate"], stats=dedup_stats)
        log.items_deduplicated = len(deduped)

        enriched = enrich(deduped, cfg.get("enrich_fetch", {}), cfg["sources"])

        labelled = label_evidence(enriched)

        classified, failures = classify_items(labelled, cfg["classification"])
        log.items_classified = len(classified)
        if failures:
            log.error_count += len(failures)
            log.errors.extend(
                {
                    "stage": "classify",
                    "item_id": f.item_id,
                    "error_type": f.error_type,
                    "error": f.error_message,
                }
                for f in failures
            )

        confidence_floor = cfg["classification"].get("confidence_floor", 0.5)
        high_impact_threshold = cfg.get("verify", {}).get("high_impact_threshold", 0.8)
        passed, held = verify_items(classified, confidence_floor, high_impact_threshold)
        log.items_held = len(held)
        if held:
            append_items(run_id, "review", held)
            logger.info("review queue persisted", extra={"run_id": run_id, "held": len(held)})

        log.metrics = run_metrics.compute(
            raw=raw,
            filtered_kept=filtered,
            labelled=labelled,
            held=held,
            passed=passed,
            dedup_stats=dedup_stats,
            high_impact_threshold=high_impact_threshold,
        )

        scored = score_items(passed, cfg["scoring"])
        log.items_scored = len(scored)

        brief = summarise(scored, cfg["summary"], review_queue=held)
        brief.run_id = run_id
        brief_path = save_brief(brief)
        logger.info("brief saved", extra={"path": str(brief_path)})
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
