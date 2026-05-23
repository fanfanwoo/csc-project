# Day 2 Agent Patterns Reference

## When to promote a module to an agent

Promote only when the module needs to:

- Choose its own next step.
- Retry with a different strategy.
- Coordinate with another module.
- Run parallel source work.
- Escalate uncertainty or risk to human review.

If none of these apply, keep it as a deterministic module.

## Suggested Day 2 agents

| Agent | Replaces / wraps | Responsibility |
|---|---|---|
| Intake agent | Source connectors | Fetch from multiple sources, handle source failure, normalise metadata |
| Normalisation agent | Filter + deduplicate | Clean, deduplicate, enrich, and prepare candidate items |
| Verification agent | Classifier + cross-check | Check source credibility, contradictions, low confidence, and missing context |
| Strategic implication agent | Signal scorer | Convert classified signals into implications and watch items |
| Presentation agent | Email/dashboard output | Route the same intelligence to email, dashboard, Slack, or API |

## LangGraph-style state sketch

```python
from typing import TypedDict, Annotated
import operator

class SignalState(TypedDict):
    raw_items: list[RawItem]
    filtered_items: list[FilteredItem]
    classified_items: list[ClassifiedItem]
    scored_items: list[ScoredItem]
    digest: str
    review_queue: list[ClassifiedItem]
    errors: Annotated[list[str], operator.add]
```

## Human review gate pattern

```python
def human_review_gate(state: SignalState) -> str:
    needs_review = [
        item for item in state["classified_items"]
        if item.human_review_flag or item.confidence < 0.7
    ]
    if needs_review:
        return "needs_review"
    return "auto_approve"
```

## Watchlist pattern

Store watchlist items by tag, domain, region, and hypothesis.
On each run, check new items against watchlist topics. Matching items can receive a configurable score boost, but the boost should be visible in `score_breakdown`.
