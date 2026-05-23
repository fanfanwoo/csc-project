# Signal Schema Reference

Use typed schemas so each module can be tested independently and later wrapped by an agent.

## RawItem

```python
@dataclass
class RawItem:
    id: str                    # stable hash of canonical URL or source id
    url: str
    canonical_url: str | None
    title: str
    body: str
    source_name: str
    source_type: str           # news, regulator, competitor, report, social, internal-note
    region: str                # AU, US, EU, global, etc.
    published_at: datetime | None
    fetched_at: datetime
    raw_metadata: dict
```

## FilteredItem

```python
@dataclass
class FilteredItem(RawItem):
    filter_reason: str | None      # None means kept
    matched_keywords: list[str]
    excluded_keywords: list[str]
```

## ClassifiedItem

```python
@dataclass
class ClassifiedItem(FilteredItem):
    domain: str                    # policy, market, auto, finance, AI, competitor, consumer, other
    signal_type: str               # threat, opportunity, weak_signal, trend, regulatory_change, competitor_move
    relevance_score: float         # 0.0-1.0
    novelty_score: float           # 0.0-1.0
    impact_score: float            # 0.0-1.0
    urgency_score: float           # 0.0-1.0
    confidence: float              # 0.0-1.0, LLM self-assessment only
    tags: list[str]
    rationale: str
    evidence_quote: str | None     # short source-supported excerpt or paraphrase
    inference_note: str | None     # what CSC inferred beyond the source facts
    human_review_flag: bool
    human_review_reason: str | None
```

## ScoredItem

```python
@dataclass
class ScoredItem(ClassifiedItem):
    strategic_score: float
    score_breakdown: dict          # relevance, impact, urgency, novelty, source_weight, confidence_penalty
    rank: int | None
```

## Suggested Day 1 scoring formula

```text
strategic_score =
  0.30 * relevance_score +
  0.25 * impact_score +
  0.20 * urgency_score +
  0.15 * novelty_score +
  0.10 * source_weight -
  confidence_penalty
```

Use the formula as a starting point. Keep weights in config, not hardcoded in module logic.
