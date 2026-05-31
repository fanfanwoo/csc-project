import os
from datetime import datetime, timezone
from pathlib import Path

from google import genai
from google.genai import types

from csc.schemas.briefs import Brief
from csc.schemas.items import ScoredItem
from csc.utils.logging import get_logger

logger = get_logger(__name__)

_PROMPT_DIR = Path(__file__).parent.parent / "prompts"


def summarise(items: list[ScoredItem], cfg: dict) -> Brief:
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    system_prompt = (_PROMPT_DIR / "summariser_prompt.txt").read_text()
    model = cfg.get("model", "gemini-2.0-flash")
    top_n = cfg.get("top_n", 5)
    audience = cfg.get("audience", "product, design, and consumer finance stakeholders")
    max_tokens = cfg.get("max_output_tokens", 2000)

    top_items = items[:top_n]
    review_items = [i for i in top_items if i.human_review_flag]
    now = datetime.now(timezone.utc)
    date_range = now.strftime("%Y-%m-%d")

    items_block = "\n\n".join(_format_item(i) for i in top_items)
    user_prompt = (
        f"Date range: {date_range}\n"
        f"Audience: {audience}\n\n"
        f"Top signals:\n{items_block}\n\n"
        "Generate the intelligence brief following the template exactly."
    )

    response = client.models.generate_content(
        model=model,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_tokens,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    markdown = response.text
    one_line = _extract_one_liner(markdown)

    logger.info("brief generated", extra={"model": model, "top_n": len(top_items)})
    return Brief(
        run_id="",
        date_range=date_range,
        generated_at=now,
        one_line_readout=one_line,
        markdown_body=markdown,
        top_signal_ids=[i.id for i in top_items],
        human_review_ids=[i.id for i in review_items],
    )


def _format_item(item: ScoredItem) -> str:
    return (
        f"[Rank {item.rank}] {item.title}\n"
        f"Source: {item.source_name} | {item.published_at} | {item.url}\n"
        f"Signal: {item.signal_type} | Domain: {item.domain} | Score: {item.strategic_score:.2f}\n"
        f"Rationale: {item.rationale}\n"
        f"Evidence: {item.evidence_quote or 'N/A'}\n"
        f"Inference: {item.inference_note or 'N/A'}\n"
        f"Human review: {'YES — ' + item.human_review_reason if item.human_review_flag else 'No'}"
    )


def _extract_one_liner(markdown: str) -> str:
    for line in markdown.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line[:200]
    return ""
