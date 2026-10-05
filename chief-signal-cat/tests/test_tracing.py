"""
LangSmith tracing helper (csc/utils/tracing.py). All offline: no Gemini call and
no trace is sent — conftest forces LANGSMITH_TRACING=false, tests that need the
"on" path set it with monkeypatch and never call through to LangSmith.
"""
import logging
import runpy
import sys
import warnings
from unittest.mock import patch

import pytest
from google import genai
from google.genai import types

from csc.utils import tracing


@pytest.fixture(autouse=True)
def reset_wrapped(monkeypatch):
    monkeypatch.setattr(tracing, "_wrapped_any", False)


def _is_wrapped(client) -> bool:
    return hasattr(client.models.generate_content, "__wrapped__")


def test_tests_run_with_tracing_off():
    import os
    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert not tracing.tracing_enabled()


@pytest.mark.parametrize("value", [None, "false", "False", "", "0"])
def test_off_returns_plain_client_without_touching_langsmith(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    else:
        monkeypatch.setenv("LANGSMITH_TRACING", value)
    with patch("langsmith.wrappers.wrap_gemini") as wrap:
        client = tracing.gemini_client("test-key")
    wrap.assert_not_called()
    assert isinstance(client, genai.Client)
    assert not _is_wrapped(client)


def test_on_wraps_client_with_daemon_upload_thread(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_USE_DAEMON", raising=False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")   # wrap_gemini's one-time beta warning
        client = tracing.gemini_client("test-key")
    assert _is_wrapped(client)
    assert tracing._wrapped_any
    import os
    assert os.environ["LANGSMITH_USE_DAEMON"] == "true"


def test_import_failure_falls_back_to_plain_client(monkeypatch, caplog):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setitem(sys.modules, "langsmith.wrappers", None)   # import raises ImportError
    with caplog.at_level(logging.WARNING, logger="csc.utils.tracing"):
        client = tracing.gemini_client("test-key")
    assert isinstance(client, genai.Client)
    assert not _is_wrapped(client)
    assert not tracing._wrapped_any
    assert "langsmith tracing unavailable" in caplog.text


def test_wrap_raising_falls_back_to_a_fresh_plain_client(monkeypatch, caplog):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    with (
        patch("langsmith.wrappers.wrap_gemini", side_effect=RuntimeError("beta broke")),
        caplog.at_level(logging.WARNING, logger="csc.utils.tracing"),
    ):
        client = tracing.gemini_client("test-key")
    assert not _is_wrapped(client)
    assert "beta broke" in str([r.__dict__ for r in caplog.records])


def test_wrapped_call_passes_gemini_the_same_config():
    """wrap_gemini turns GenerateContentConfig into vars(config) before the real
    call. Through the real Models.generate_content, the request Gemini would get
    must still carry the config CSC built. Stopped at _generate_content: no network.
    """
    from google.genai import models
    from langsmith import tracing_context
    from langsmith.wrappers import wrap_gemini

    config = types.GenerateContentConfig(
        system_instruction="sys",
        max_output_tokens=1024,
        response_mime_type="application/json",
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
    sent = []

    def fake_generate(self, *, model, contents, config):
        sent.append(config)
        raise RuntimeError("stop before the network")

    with patch.object(models.Models, "_generate_content", fake_generate), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        client = wrap_gemini(genai.Client(api_key="test-key"))
        with tracing_context(enabled=False), pytest.raises(RuntimeError, match="stop before"):
            client.models.generate_content(model="m", contents="hi", config=config)

    assert types.GenerateContentConfig.model_validate(sent[0]) == config


def test_flush_is_a_noop_when_nothing_was_wrapped():
    with patch("langsmith.run_trees.get_cached_client") as get_client:
        tracing.flush_traces()
    get_client.assert_not_called()


def test_flush_waits_a_bounded_time(monkeypatch):
    monkeypatch.setattr(tracing, "_wrapped_any", True)
    with patch("langsmith.run_trees.get_cached_client") as get_client:
        tracing.flush_traces()
    get_client.return_value.flush.assert_called_once_with(timeout=tracing.FLUSH_TIMEOUT_SECONDS)


def test_flush_failure_only_warns(monkeypatch, caplog):
    monkeypatch.setattr(tracing, "_wrapped_any", True)
    with (
        patch("langsmith.run_trees.get_cached_client", side_effect=RuntimeError("down")),
        caplog.at_level(logging.WARNING, logger="csc.utils.tracing"),
    ):
        tracing.flush_traces()   # must not raise
    assert "langsmith flush failed" in caplog.text


def test_scheduler_main_flushes_even_when_the_run_exits_nonzero():
    with (
        patch("csc.run.run_pipeline", side_effect=RuntimeError("down")),
        patch("time.sleep"),
        patch("csc.pipeline.send_email.send_plain_text"),
        patch("csc.utils.tracing.flush_traces") as flush,
        warnings.catch_warnings(),
    ):
        warnings.simplefilter("ignore", RuntimeWarning)   # runpy: module already imported
        with pytest.raises(SystemExit) as exc:
            runpy.run_module("csc.pipeline.scheduler", run_name="__main__")
    assert exc.value.code == 1
    flush.assert_called_once_with()


def test_manual_run_main_flushes_even_when_the_run_raises():
    # runpy re-executes csc.run, so run_pipeline is the real one — fail it at load_config.
    with (
        patch("csc.config.load_config", side_effect=RuntimeError("down")),
        patch("csc.utils.tracing.flush_traces") as flush,
        patch.object(sys, "argv", ["csc.run", "--dry-run"]),
        warnings.catch_warnings(),
    ):
        warnings.simplefilter("ignore", RuntimeWarning)   # runpy: module already imported
        with pytest.raises(RuntimeError, match="down"):
            runpy.run_module("csc.run", run_name="__main__")
    flush.assert_called_once_with()
