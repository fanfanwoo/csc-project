import argparse
import uuid
from datetime import datetime

from csc.config import load_config
from csc.pipeline.fetch_sources import fetch_all_sources
from csc.pipeline.filter_items import filter_items
from csc.pipeline.deduplicate import deduplicate
from csc.pipeline.decisions import (
    classify_decisions,
    dedupe_decisions,
    filter_decisions,
    summarise_decisions,
    verify_decisions,
)
from csc.pipeline.enrich_fetch import enrich
from csc.pipeline.evidence_state import label_evidence
from csc.pipeline.classify import classify_items
from csc.pipeline.verify import verify_items
from csc.pipeline import run_metrics
from csc.pipeline.score import score_items
from csc.pipeline.source_health import assess_sources
from csc.pipeline.summarise import summarise
from csc.pipeline.send_email import send_email
from csc.schemas.runs import RunLog
from csc.storage.jsonl_store import append_decisions, append_items, append_run_log, save_brief
from csc.utils.logging import get_logger
from csc.utils.report_tz import report_tz
from csc.utils.tracing import flush_traces, pipeline_trace

logger = get_logger(__name__)


class AllSourcesFailedError(RuntimeError):
    """No configured source returned any item, so there is nothing to brief."""


def run_pipeline(dry_run: bool = False, *, trigger: str = "manual", attempt: int | None = None) -> RunLog:
    """One pipeline attempt, traced as a `csc.run` parent when LangSmith tracing is on.

    trigger: "scheduled" (csc.pipeline.scheduler) or "manual". attempt: the
    scheduler's attempt number; None for manual runs.
    """
    run_id = str(uuid.uuid4())
    metadata = {
        "run_id": run_id,
        "run_date": datetime.now().astimezone().date().isoformat(),
        "trigger": trigger,
        "dry_run": dry_run,
    }
    if attempt is not None:
        metadata["attempt"] = attempt
    with pipeline_trace(metadata):
        return _run_pipeline(run_id, dry_run)


def _run_pipeline(run_id: str, dry_run: bool) -> RunLog:
    started_at = datetime.utcnow()
    log = RunLog(run_id=run_id, started_at=started_at, status="started")
    logger.info("pipeline started", extra={"run_id": run_id})

    try:
        cfg = load_config()

        raw = fetch_all_sources(cfg["sources"])
        log.items_fetched = len(raw)

        # Judged on the raw fetch, before any filter: a source that returned
        # nothing must be distinguishable from one whose items were filtered out.
        # Newest-item dates render in the report timezone, like the brief's own.
        health = assess_sources(raw, cfg["sources"], tz=report_tz(cfg))
        if not raw:
            # Every source failed or came back empty. Building a brief from nothing
            # reads as "a quiet day"; failing makes the scheduler retry, then alert.
            raise AllSourcesFailedError(
                f"every source fetch failed or came back empty: 0 items from {len(cfg['sources'])} configured sources"
            )

        filtered_all = filter_items(raw, cfg["filter"], cfg["sources"])
        filtered = [i for i in filtered_all if i.filter_status != "dropped"]
        log.items_filtered = len(filtered)

        dedup_stats: dict = {}
        deduped = deduplicate(filtered, cfg["deduplicate"], stats=dedup_stats)
        log.items_deduplicated = len(deduped)

        # One line per fetched item: filter drops, then dedupe kept/duplicate.
        decisions = filter_decisions(filtered_all) + dedupe_decisions(filtered, deduped)
        append_decisions(run_id, decisions)
        log.decisions = summarise_decisions(decisions)
        logger.info("decisions recorded", extra={"run_id": run_id, "by_source": log.decisions})

        enriched = enrich(deduped, cfg.get("enrich_fetch", {}), cfg["sources"])

        labelled = label_evidence(enriched)

        classified, failures = classify_items(labelled, cfg["classification"])
        log.items_classified = len(classified)
        append_decisions(run_id, classify_decisions(labelled, classified, failures))
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
        # What the gate saw for every item, passed or held: scores of passed items
        # are not stored anywhere else.
        append_decisions(run_id, verify_decisions(passed, held))
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

        brief = summarise(
            scored,
            cfg["summary"],
            review_queue=held,
            source_health=health,
            report_timezone=report_tz(cfg),
        )
        brief.run_id = run_id
        brief_path = save_brief(brief)
        logger.info("brief saved", extra={"path": str(brief_path)})
        if dry_run:
            logger.info(
                "dry-run: email send skipped",
                extra={"run_id": run_id, "recipients": cfg["email"].get("recipients", [])},
            )
        else:
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
    parser = argparse.ArgumentParser(description="Run the Chief Signal Cat pipeline.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the full pipeline but skip sending email (still fetches, classifies, saves brief).",
    )
    args = parser.parse_args()
    try:
        run_pipeline(dry_run=args.dry_run)
    finally:
        # Bounded: an unreachable LangSmith can't hang a manual run.
        flush_traces()
