"""
Review-queue recurrence report — the corroboration-agent trigger watch.

The corroboration agent (deferred, see ADR-0003) earns its trigger only when live
runs *repeatedly* hold the same single-source signal — one a second, independent
source would have resolved. A one-off hold is normal routing; recurrence across
runs is the evidence that deterministic in-run dedup is no longer enough.

This tool reads the per-run review-queue JSONL files (data/review/{run_id}.jsonl)
and clusters held items by **exact URL** across runs, counting how many distinct
runs each signal was held in. It reports only items held on a **single-source**
reason (single_source_high_impact, headline_only_high_impact) — sensitive_domain
marks-but-passes, and large_inference_leap was retired in v1a.

Clustering is on canonical_url (exact), **never fuzzy title**. Evergreen finance
templates ("inflation puts rate hikes back on the table") recur every quarter with a
near-identical headline but are *distinct events* at *distinct URLs*. Fuzzy-title
clustering would read them as one recurring signal and manufacture false recurrence.
Telling near-identical-but-distinct events apart is the corroboration agent's hard
problem (its judge-match step) — it must not be smuggled into this watch. So recurrence
here means literally the same article held run after run.

Read-only. No pipeline state is touched.

    python3 -m csc.tools.review_recurrence              # default data/review, min 2 runs
    python3 -m csc.tools.review_recurrence --min-runs 3
    python3 -m csc.tools.review_recurrence --data-dir /path/to/review
"""

import argparse
import glob
import json
from dataclasses import dataclass, field
from pathlib import Path

# Hold reasons a second source could resolve. sensitive_domain is excluded (it marks,
# it does not hold); large_inference_leap is excluded (retired in v1a).
CORROBORATION_REASONS = {"single_source_high_impact", "headline_only_high_impact"}


@dataclass
class Cluster:
    key: str                                  # canonical_url (or url) — the exact identity
    example_title: str                        # a human-readable title for display only
    run_ids: set[str] = field(default_factory=set)
    reasons: set[str] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)
    categories: set[str] = field(default_factory=set)   # evidence_category values seen

    @property
    def run_count(self) -> int:
        return len(self.run_ids)

    @property
    def is_corroboration_candidate(self) -> bool:
        # A second source only helps when the signal isn't already from an
        # authoritative source. ASIC (official) IS the source — you don't corroborate
        # the regulator, and Phase 0 exempts official full-body items from this hold.
        return bool(self.categories - {"official"})


def signal_key(item: dict) -> str:
    """Exact identity of a held signal: canonical_url, falling back to url. Never the
    title — different events can share a headline template."""
    return item.get("canonical_url") or item.get("url") or ""


def _held_single_source_items(path: str) -> list[dict]:
    """Held items in one run-file whose reasons include a corroboration reason."""
    items = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        reasons = set((d.get("human_review_reason") or "").split(", "))
        if reasons & CORROBORATION_REASONS:
            items.append(d)
    return items


def build_clusters(run_files: dict[str, list[dict]]) -> list[Cluster]:
    """Cluster held single-source items across runs by exact URL.

    `run_files` maps run_id -> list of held item dicts. An item joins the cluster
    with the same signal_key (canonical_url / url), else starts one. No fuzzy match:
    a near-identical headline at a different URL is a different signal.
    """
    clusters: dict[str, Cluster] = {}
    for run_id, items in run_files.items():
        for item in items:
            item_reasons = set((item.get("human_review_reason") or "").split(", ")) & CORROBORATION_REASONS
            if not item_reasons:
                continue  # only single-source holds count; ignore anything else passed in
            key = signal_key(item)
            if not key:
                continue
            cluster = clusters.get(key)
            if cluster is None:
                cluster = Cluster(key=key, example_title=item.get("title", ""))
                clusters[key] = cluster
            cluster.run_ids.add(run_id)
            cluster.reasons.update(item_reasons)
            if item.get("source_name"):
                cluster.sources.add(item["source_name"])
            if item.get("evidence_category"):
                cluster.categories.add(item["evidence_category"])
    return list(clusters.values())


def load_runs(data_dir: str) -> dict[str, list[dict]]:
    """Map run_id -> held single-source items, for every review JSONL in data_dir."""
    runs: dict[str, list[dict]] = {}
    for path in glob.glob(str(Path(data_dir) / "*.jsonl")):
        run_id = Path(path).stem
        runs[run_id] = _held_single_source_items(path)
    return runs


def recurring(clusters: list[Cluster], min_runs: int) -> list[Cluster]:
    out = [c for c in clusters if c.run_count >= min_runs]
    out.sort(key=lambda c: c.run_count, reverse=True)
    return out


def format_report(runs: dict[str, list[dict]], clusters: list[Cluster], min_runs: int) -> str:
    held_total = sum(len(v) for v in runs.values())
    recurrences = recurring(clusters, min_runs)
    candidates = [c for c in recurrences if c.is_corroboration_candidate]
    official_only = [c for c in recurrences if not c.is_corroboration_candidate]

    lines = [
        "Review-queue recurrence — corroboration-agent trigger watch",
        f"  runs scanned: {len(runs)} | single-source holds: {held_total} | distinct signals: {len(clusters)}",
        f"  recurring in >= {min_runs} runs: {len(recurrences)} "
        f"({len(candidates)} corroboration candidates, {len(official_only)} official-only)",
        "",
    ]

    if candidates:
        lines.append("  >> TRIGGER CANDIDATES — non-official single-source signals held repeatedly")
        lines.append("     (a second independent source would likely have resolved these):")
        for c in candidates:
            lines.append(f"    [{c.run_count} runs] {c.example_title!r}")
            lines.append(f"             reasons={sorted(c.reasons)} sources={sorted(c.sources)}")
        lines.append("")
    else:
        lines.append("  No NON-official recurring single-source signal yet — trigger not met. Keep watching.")
        lines.append("")

    if official_only:
        lines.append("  (Ignored: official-source recurrences — ASIC is authoritative, not a")
        lines.append("   corroboration target; Phase 0 now exempts official full-body items.)")
        for c in official_only:
            lines.append(f"    [{c.run_count} runs] {c.example_title!r}  sources={sorted(c.sources)}")

    return "\n".join(lines)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Review-queue recurrence report.")
    parser.add_argument("--data-dir", default="data/review", help="dir of review JSONL files")
    parser.add_argument("--min-runs", type=int, default=2, help="recurrence threshold")
    args = parser.parse_args(argv)

    runs = load_runs(args.data_dir)
    clusters = build_clusters(runs)
    print(format_report(runs, clusters, args.min_runs))


if __name__ == "__main__":
    main()
