"""
Every fetch failed → the run fails visibly instead of sending an empty brief.

An empty fetch used to flow through every stage and produce a brief with no
signals, which reads as "a quiet day". Now run_pipeline raises after source
health is assessed: no brief, no email, a failed run log, and the scheduler's
retry-then-alert path takes over with the reason in the alert body.
"""
import json
from unittest.mock import patch

import pytest

from csc.run import AllSourcesFailedError, run_pipeline

CFG = {
    "sources": [{"name": "ASIC Media"}, {"name": "Google News"}],
    "filter": {}, "deduplicate": {}, "classification": {}, "scoring": {}, "summary": {}, "email": {},
}


def test_empty_fetch_fails_the_run_without_a_brief_or_email(isolate_data_dir):
    with (
        patch("csc.run.load_config", return_value=CFG),
        patch("csc.run.fetch_all_sources", return_value=[]),
        patch("csc.run.assess_sources", return_value=[]) as mock_assess,
        patch("csc.run.classify_items") as mock_classify,
        patch("csc.run.save_brief") as mock_save,
        patch("csc.run.send_email") as mock_send,
        pytest.raises(AllSourcesFailedError, match="0 items from 2 configured sources"),
    ):
        run_pipeline()

    mock_assess.assert_called_once()
    mock_classify.assert_not_called()
    mock_save.assert_not_called()
    mock_send.assert_not_called()

    (log_file,) = (isolate_data_dir / "logs").iterdir()
    run_log = json.loads(log_file.read_text())
    assert run_log["status"] == "failed"
    assert "every source fetch failed or came back empty" in run_log["errors"][-1]["error"]


def test_the_alert_says_why(monkeypatch):
    monkeypatch.setattr("csc.pipeline.scheduler.time.sleep", lambda _: None)
    cfg = {"email": {"alert_address": "alert@example.com"}}
    with (
        patch("csc.pipeline.scheduler.run_pipeline",
              side_effect=AllSourcesFailedError("every source fetch failed: 0 items from 3 configured sources")),
        patch("csc.pipeline.scheduler.load_config", return_value=cfg),
        patch("csc.pipeline.scheduler.send_plain_text") as mock_send,
        pytest.raises(SystemExit),
    ):
        from csc.pipeline.scheduler import run_once
        run_once()

    body = mock_send.call_args.kwargs["body"]
    assert "Last error: every source fetch failed: 0 items from 3 configured sources" in body
