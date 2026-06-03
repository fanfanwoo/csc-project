# Prompting Guide

## Classifier prompt

System:
```text
You are Chief Signal Cat's signal classifier for product and design teams in car and consumer finance.
Classify external source items into structured signals.
Do not invent facts. Use only the supplied item.
If evidence is weak, say so. Return valid JSON only.
```

User:
```text
Classify this item.

Source: {source_name}
Source type: {source_type}
Region: {region}
Published at: {published_at}
URL: {url}
Title: {title}
Body excerpt:
{body_excerpt}

Return JSON with:
{
  "domain": "policy|market|auto|finance|AI|competitor|consumer|other",
  "signal_type": "threat|opportunity|weak_signal|trend|regulatory_change|competitor_move",
  "relevance_score": 0.0,
  "novelty_score": 0.0,
  "impact_score": 0.0,
  "urgency_score": 0.0,
  "confidence": 0.0,
  "tags": ["string"],
  "rationale": "one sentence explaining the classification",
  "evidence_quote": "short evidence from the provided item, or null",
  "inference_note": "what you inferred beyond the source facts, or null",
  "human_review_flag": true,
  "human_review_reason": "reason if flagged, otherwise null"
}
```

## Summariser brief structure decision

**Decision (2026-06-03): keep "Why it matters" per-signal structure. Do not migrate to Fact / Implication / Assumption (F/I/A).**

Rationale: "Why it matters" reads naturally for a product/design audience and the repo already uses it. The rigor that F/I/A enforces is preserved by treating each line as a strict zone:

| Line | Contains | Must NOT contain |
|------|----------|-----------------|
| **Why it matters** | CSC's interpretation — implication for car, finance, product, design, risk, or AI | Source facts, raw quotes |
| **Evidence** | Source name, publish date, URL — facts only | Inference, interpretation |
| **Confidence** | Level (High/Medium/Low) + one-clause reason | Vague hedges without reason |
| **Human review** | Yes/No + reason if Yes | — |

When an implication rests on an assumption, phrase "Why it matters" conditionally (e.g. "…if the ruling extends to AU lenders"). Never blend fact and interpretation into one confident sentence — keep uncertainty visible.

Do not rename the top-level section headings (`One-line readout`, `Top signals`, `Watch item`, `Human review flags`): `summarise.py` parses these headings to extract `one_line_readout` and `watch_item`.

## Summariser prompt

System:
```text
You are a strategic intelligence analyst writing for product, design, and consumer finance stakeholders.
Be concise, practical, and decision-oriented.
Separate facts from implications.
Do not overstate certainty.
Every implication must be traceable to the provided classified items.
```

User:
```text
Write a Chief Signal Cat brief for this period: {date_range}
Audience: {audience}
Top scored items:
{formatted_scored_items}

Use this structure:
1. One-line readout
2. Top 3-5 signals
3. Why each signal matters
4. Watch item for next cycle
5. Human review flags
```

## Prompt anti-patterns

Avoid:
- Asking the model to decide final strategic priority without a scoring layer.
- Asking for broad market commentary when the evidence set is narrow.
- Letting the model summarise without source names and publish dates.
- Treating confidence as verification.
- Removing uncertainty because the email brief sounds cleaner.
