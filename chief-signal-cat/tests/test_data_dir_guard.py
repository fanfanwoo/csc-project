"""
Tests for the conftest data/ guard: store writes land in tmp_path, and the
snapshot diff reports real-dir changes.
"""
from datetime import datetime
from pathlib import Path

from conftest import REAL_DATA_DIR, diff_snapshots, snapshot

import csc.storage.jsonl_store as store
from csc.schemas.runs import RunLog


def test_store_redirected_to_tmp_path(isolate_data_dir):
    assert store._DATA_DIR == isolate_data_dir
    assert REAL_DATA_DIR not in store._DATA_DIR.parents


def test_store_writes_land_in_tmp_path(isolate_data_dir):
    store.append_items("run-x", "review", [])
    store.append_run_log(RunLog(run_id="run-x", started_at=datetime(2026, 1, 1), status="started"))
    assert (isolate_data_dir / "review" / "run-x.jsonl").exists()
    assert (isolate_data_dir / "logs" / "run-x.jsonl").exists()


def test_diff_reports_added_removed_modified(tmp_path: Path):
    (tmp_path / "keep.jsonl").write_text("a")
    (tmp_path / "gone.jsonl").write_text("a")
    before = snapshot(tmp_path)

    (tmp_path / "keep.jsonl").write_text("changed")
    (tmp_path / "gone.jsonl").unlink()
    (tmp_path / "new.jsonl").write_text("a")

    assert diff_snapshots(before, snapshot(tmp_path)) == [
        "added    new.jsonl",
        "modified keep.jsonl",
        "removed  gone.jsonl",
    ]


def test_diff_ignores_ds_store(tmp_path: Path):
    before = snapshot(tmp_path)
    (tmp_path / ".DS_Store").write_text("x")
    assert diff_snapshots(before, snapshot(tmp_path)) == []


def test_snapshot_missing_dir_is_empty(tmp_path: Path):
    assert snapshot(tmp_path / "nope") == {}
