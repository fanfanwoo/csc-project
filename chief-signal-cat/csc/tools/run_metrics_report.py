"""
Run-metrics report — read the v1b operational metrics across runs.

Reads the per-run logs (data/logs/{run_id}.jsonl), each carrying RunLog.metrics
(see csc/pipeline/run_metrics.py), and prints them newest-first so you can watch
publisher value, filter pressure, enrich health, and Phase 0/3 firing over time.

Read-only.

    python3 -m csc.tools.run_metrics_report                 # default data/logs
    python3 -m csc.tools.run_metrics_report --limit 20
    python3 -m csc.tools.run_metrics_report --data-dir /path/to/logs
"""

import argparse
import glob
import json
from pathlib import Path

# Columns shown, in order. Keys come from run_metrics.compute().
_COLUMNS = [
    ("pub_fetch", "publisher_fetched"),
    ("pub_drop", "publisher_dropped_filter"),
    ("enr_ok", "enrich_success"),
    ("enr_fail", "enrich_failed"),
    ("enr_exc", "enrich_excerpt"),
    ("hl_held", "held_headline_only_high_impact"),
    ("off_rel", "official_released"),
    ("pub>agg", "dedup_publisher_over_aggregator"),
]


def load_run_logs(data_dir: str) -> list[dict]:
    """Load run-log dicts (newest first by started_at) that have a metrics block."""
    runs = []
    for path in glob.glob(str(Path(data_dir) / "*.jsonl")):
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get("metrics"):
                runs.append(d)
    runs.sort(key=lambda d: d.get("started_at", ""), reverse=True)
    return runs


def format_report(runs: list[dict], limit: int) -> str:
    if not runs:
        return "No runs with metrics yet. Run the pipeline, then re-check."

    header = "  ".join(["run".ljust(8), "date".ljust(10)] + [c.rjust(8) for c, _ in _COLUMNS])
    lines = [f"Run metrics — {len(runs)} run(s) with metrics, newest first", "", header]
    for d in runs[:limit]:
        m = d["metrics"]
        run_short = (d.get("run_id") or "")[:8]
        date = (d.get("started_at") or "")[:10]
        cells = [str(m.get(key, "-")).rjust(8) for _, key in _COLUMNS]
        lines.append("  ".join([run_short.ljust(8), date.ljust(10)] + cells))
    return "\n".join(lines)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Run-metrics report across runs.")
    parser.add_argument("--data-dir", default="data/logs", help="dir of run-log JSONL files")
    parser.add_argument("--limit", type=int, default=20, help="max runs to show")
    args = parser.parse_args(argv)
    print(format_report(load_run_logs(args.data_dir), args.limit))


if __name__ == "__main__":
    main()
