from apscheduler.schedulers.blocking import BlockingScheduler

from csc.config import load_config
from csc.run import run_pipeline
from csc.utils.logging import get_logger

logger = get_logger(__name__)


def start_scheduler() -> None:
    cfg = load_config()
    cron_expr = cfg["pipeline"].get("schedule_cron", "0 7 * * *")
    minute, hour, day, month, dow = cron_expr.split()

    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_pipeline,
        "cron",
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=dow,
    )
    logger.info("scheduler started", extra={"cron": cron_expr})
    scheduler.start()


if __name__ == "__main__":
    start_scheduler()
