"""
LangSmith tracing for the Gemini calls (classify, summarise).

Opt-in: only LANGSMITH_TRACING=true wraps the client. Unset or anything else and
langsmith is never imported — the plain genai.Client is used exactly as before.
Tracing must never break or delay the pipeline: a failed import or wrap logs a
warning and falls back to the plain client, and flush_traces() waits a bounded time.

langsmith.wrappers.wrap_gemini is labelled BETA in langsmith 0.14.x.
"""

import os

from google import genai

from csc.utils.logging import get_logger

logger = get_logger(__name__)

# Upper bound on the exit-time wait for pending traces.
FLUSH_TIMEOUT_SECONDS = 10.0

_wrapped_any = False


def tracing_enabled() -> bool:
    return os.environ.get("LANGSMITH_TRACING", "").strip().lower() == "true"


def gemini_client(api_key: str) -> genai.Client:
    """A genai.Client, wrapped for LangSmith tracing when LANGSMITH_TRACING=true."""
    global _wrapped_any
    if not tracing_enabled():
        return genai.Client(api_key=api_key)
    try:
        # langsmith's upload thread is non-daemon by default and drains its queue
        # at interpreter exit, so an unreachable LangSmith could hold the process
        # open through HTTP timeouts and retries. A daemon thread lets the process
        # exit after flush_traces()' bounded wait; unsent traces are dropped.
        os.environ.setdefault("LANGSMITH_USE_DAEMON", "true")
        from langsmith.wrappers import wrap_gemini

        client = wrap_gemini(genai.Client(api_key=api_key))
        _wrapped_any = True
        return client
    except Exception as exc:
        logger.warning("langsmith tracing unavailable; using plain Gemini client", extra={"error": str(exc)})
        # wrap_gemini patches in place, so a failure part-way leaves that client
        # half-wrapped — build a fresh one.
        return genai.Client(api_key=api_key)


def flush_traces(timeout: float = FLUSH_TIMEOUT_SECONDS) -> None:
    """Send pending traces, waiting at most `timeout` seconds. No-op if nothing was traced."""
    if not _wrapped_any:
        return
    try:
        from langsmith.run_trees import get_cached_client

        get_cached_client().flush(timeout=timeout)
    except Exception as exc:
        logger.warning("langsmith flush failed", extra={"error": str(exc)})
