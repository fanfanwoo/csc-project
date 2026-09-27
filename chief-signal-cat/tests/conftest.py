"""
Shared test fixtures.

Guard: no test may write under the real chief-signal-cat/data/ directory.
Tests that ran run_pipeline() without patching every store call used to leak
fixture items into data/review/, which then showed up as fake recurrence in
csc.tools.review_recurrence. Every test now gets jsonl_store pointed at
tmp_path, and the real data/ tree is snapshotted before and after each test —
any added, removed or modified path fails the test.
"""
from pathlib import Path

import pytest

REAL_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Written by the OS, not by tests.
_IGNORED_NAMES = {".DS_Store"}


def snapshot(root: Path) -> dict[str, tuple[int, int]]:
    """Map every path under root (relative) to (size, mtime_ns)."""
    if not root.exists():
        return {}
    snap = {}
    for p in root.rglob("*"):
        if p.name in _IGNORED_NAMES:
            continue
        st = p.stat()
        snap[str(p.relative_to(root))] = (st.st_size if p.is_file() else 0, st.st_mtime_ns)
    return snap


def diff_snapshots(before: dict, after: dict) -> list[str]:
    """Human-readable list of changes between two snapshots, sorted."""
    changes = [f"added    {p}" for p in after.keys() - before.keys()]
    changes += [f"removed  {p}" for p in before.keys() - after.keys()]
    changes += [f"modified {p}" for p in before.keys() & after.keys() if before[p] != after[p]]
    return sorted(changes)


@pytest.fixture(autouse=True)
def isolate_data_dir(tmp_path, monkeypatch):
    """Redirect jsonl_store to tmp_path and fail if the real data/ dir changes."""
    monkeypatch.setattr("csc.storage.jsonl_store._DATA_DIR", tmp_path / "data")
    before = snapshot(REAL_DATA_DIR)
    yield tmp_path / "data"
    changes = diff_snapshots(before, snapshot(REAL_DATA_DIR))
    if changes:
        pytest.fail(
            f"test wrote under the real data dir {REAL_DATA_DIR}:\n  " + "\n  ".join(changes),
            pytrace=False,
        )
