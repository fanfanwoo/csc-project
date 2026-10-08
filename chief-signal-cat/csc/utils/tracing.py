"""
LangSmith tracing for the pipeline: one `csc.run` parent per pipeline attempt, with
the Gemini calls (`csc.classify`, `csc.summarise`) nested under it.

Opt-in: only LANGSMITH_TRACING=true traces. Unset or anything else and langsmith is
never imported — the plain genai.Client is used and pipeline_trace() does nothing.
Tracing must never break or delay the pipeline: a failed import, wrap or trace logs
a warning and the run continues untraced, an exception from the pipeline propagates
unchanged, and flush_traces() waits a bounded time.

langsmith.wrappers.wrap_gemini is labelled BETA in langsmith 0.14.x.
"""

import os
from typing import Any, Mapping

from google import genai

from csc.utils.logging import get_logger

logger = get_logger(__name__)

# Upper bound on the exit-time wait for pending traces.
FLUSH_TIMEOUT_SECONDS = 10.0

PIPELINE_TRACE_NAME = "csc.run"

_traced_any = False


def tracing_enabled() -> bool:
    return os.environ.get("LANGSMITH_TRACING", "").strip().lower() == "true"


def _use_daemon_upload_thread() -> None:
    # langsmith's upload thread is non-daemon by default and drains its queue
    # at interpreter exit, so an unreachable LangSmith could hold the process
    # open through HTTP timeouts and retries. A daemon thread lets the process
    # exit after flush_traces()' bounded wait; unsent traces are dropped.
    os.environ.setdefault("LANGSMITH_USE_DAEMON", "true")


def gemini_client(api_key: str, *, name: str, metadata: Mapping[str, Any] | None = None) -> genai.Client:
    """A genai.Client, wrapped for LangSmith tracing when LANGSMITH_TRACING=true.

    `name` is the run name of each generate_content call (e.g. "csc.classify");
    `metadata` is attached to every call made through this client.
    """
    global _traced_any
    if not tracing_enabled():
        return genai.Client(api_key=api_key)
    try:
        _use_daemon_upload_thread()
        from langsmith.wrappers import wrap_gemini

        tracing_extra = {"metadata": dict(metadata)} if metadata else None
        client = wrap_gemini(genai.Client(api_key=api_key), tracing_extra=tracing_extra, chat_name=name)
        _traced_any = True
        return client
    except Exception as exc:
        logger.warning("langsmith tracing unavailable; using plain Gemini client", extra={"error": str(exc)})
        # wrap_gemini patches in place, so a failure part-way leaves that client
        # half-wrapped — build a fresh one.
        return genai.Client(api_key=api_key)


class _PipelineTrace:
    """Context manager behind pipeline_trace(). A class, not @contextmanager, so an
    exception from the pipeline propagates untouched — never re-raised by us."""

    def __init__(self, metadata: Mapping[str, Any]):
        self._metadata = dict(metadata)
        self._trace = None

    def __enter__(self) -> "_PipelineTrace":
        global _traced_any
        if not tracing_enabled():
            return self
        try:
            _use_daemon_upload_thread()
            from langsmith import trace

            run_trace = trace(PIPELINE_TRACE_NAME, "chain", metadata=self._metadata)
            run_trace.__enter__()
        except Exception as exc:
            logger.warning("langsmith run trace unavailable; running untraced", extra={"error": str(exc)})
            return self
        self._trace = run_trace
        _traced_any = True
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if self._trace is not None:
            try:
                # Records exc_value as the run's error; never suppresses it.
                self._trace.__exit__(exc_type, exc_value, traceback)
            except Exception as exc:
                logger.warning("langsmith run trace failed to close", extra={"error": str(exc)})
        return False


def pipeline_trace(metadata: Mapping[str, Any]) -> _PipelineTrace:
    """Parent `csc.run` trace for one pipeline attempt; a no-op when tracing is off."""
    return _PipelineTrace(metadata)


def flush_traces(timeout: float = FLUSH_TIMEOUT_SECONDS) -> None:
    """Send pending traces, waiting at most `timeout` seconds. No-op if nothing was traced."""
    if not _traced_any:
        return
    try:
        from langsmith.run_trees import get_cached_client

        get_cached_client().flush(timeout=timeout)
    except Exception as exc:
        logger.warning("langsmith flush failed", extra={"error": str(exc)})
