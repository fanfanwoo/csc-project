---
name: chief-signal-cat
description: Use for Chief Signal Cat (CSC / Signal Cat): Day 1 signal pipeline and Day 2 agents for external market, car, finance, policy, AI signals.
---

# Chief Signal Cat (CSC)

## Purpose

Chief Signal Cat is an external strategic signal intelligence system for product and design teams in car and consumer finance.

- CDC listens inward: customer feedback, reviews, support themes, observed pain points.
- CSC listens outward: market, policy, auto, finance, technology, competitor, and AI signals.
- The combined direction is a unified intelligence layer: internal evidence + external signals + human judgement.

Use this skill when working on CSC architecture, Day 1 pipeline design, Day 2 agent uplift, signal schemas, prompt design, source selection, scoring, summarisation, code review, or intelligence brief output.

## Core principle

Build deterministic modules first. Promote modules to agents only when orchestration creates real value.

A module becomes an agent only when it needs to choose a next step, retry with a different strategy, coordinate with another module, run parallel work, or escalate to human review.

## Three-day roadmap

| Stage | Name | Goal | Output |
|---|---|---|---|
| Day 1 | Deterministic MVP | Prove the pipeline end to end | Daily/3-day email brief |
| Day 2 | Agentic orchestration | Add intake, normalisation, verification, and presentation agents | Multi-source verified brief |
| Day 3 | Strategic intelligence layer | Connect CSC with CDC and decision workflows | Dashboard, brief, API, decision log |

## Day 1 pipeline

```text
Scheduler -> Source connector -> Filter rules -> Deduplicate ->
LLM classifier -> Signal scorer -> LLM summariser -> Email output
```

Day 1 should stay small: one region, one or two source types, daily capture, 3-day synthesis window, and an inspectable brief.

## Non-negotiable architecture rules

1. **Schema first**: define data contracts before writing modules. See `chief-signal-cat/csc/schemas/items.py` (authoritative).
2. **No LLM before filtering**: reduce obvious noise with deterministic logic before classification.
3. **Functions before classes**: Day 1 modules should be simple functions: `process(items: list[X]) -> list[Y]`.
4. **Evidence always travels with the signal**: store source URL, title, source name, published date, fetched date, and extraction notes.
5. **Confidence is not truth**: confidence is an LLM self-assessment, not proof. High-impact signals still need verification.
6. **No unsupported strategic claims**: every implication must be traceable to source evidence or explicitly marked as inference.
7. **Everything dropped must have a reason**: log dropped items with deterministic reason codes.
8. **Append-only signal log**: preserve raw, filtered, classified, scored, and summarised records for audit and future evaluation.

## Module responsibilities

| Module | Job | Rules |
|---|---|---|
| Scheduler | Trigger the run | Keep dumb; no business logic |
| Source connector | Fetch external items | Return `RawItem`; handle retries and failed sources |
| Filter rules | Remove noise | Use allowlists, blocklists, recency, region, and domain rules |
| Deduplicate | Merge repeated stories | Exact URL first; fuzzy title/body second |
| LLM classifier | Classify candidate signals | Return structured JSON only; include confidence and rationale |
| Signal scorer | Rank strategic importance | Rule-based; do not ask LLM to decide final priority alone |
| LLM summariser | Produce decision-ready brief | Highlight implications, uncertainty, and watch items |
| Email output | Send the brief | Plain text first; HTML optional; include source links |

## Human review gates

Escalate or flag a signal when any of these apply:

- Regulatory, legal, compliance, lending, privacy, or customer harm implications.
- High commercial impact but only one weak source.
- Low classifier confidence or vague article evidence.
- Contradictory sources or rapidly evolving story.
- Major inference needed to connect the signal to product/design decisions.
- The signal could cause a team to change roadmap, risk appetite, pricing, lending process, or customer messaging.

## Default brief structure

Use this structure unless the user asks otherwise:

```markdown
# Chief Signal Cat Brief — {date range}

## One-line readout
{The most important strategic interpretation in one sentence.}

## Top signals
1. **{Signal title}** — {what happened}.  
   **Why it matters:** {specific implication for car, finance, product, design, risk, or AI}.  
   **Evidence:** {source name, publish date, URL}.  
   **Confidence:** {high/medium/low + reason}.

## Watch item
{One thing to monitor next cycle and why.}

## Human review flags
{Items that should not be treated as final intelligence without review.}
```

## Prompting and evaluation

- For classifier and summariser prompts, use `references/prompting-guide.md`.
- For Day 2 agent patterns, use `references/day2-agent-patterns.md`.
- For schema fields and scoring rules, see `chief-signal-cat/csc/schemas/items.py`.
- For output review, use `references/review-checklist.md`.

## Code review checklist

When reviewing CSC code, check:

1. Do modules use the agreed schemas?
2. Is the LLM called only after filtering/deduplication?
3. Are failed fetches, dropped items, and LLM errors logged?
4. Are API keys, thresholds, source lists, and model names kept in config?
5. Does each LLM output have JSON validation and fallback handling?
6. Are source URL, publish date, and fetched date preserved?
7. Are high-impact/low-confidence signals routed to human review?
8. Are unit tests built around fixture items and expected classifications?
9. Can the module be wrapped by a Day 2 agent without internal rewriting?

## Day 2 direction

Day 2 promotes selected modules into agents:

- Source connector -> Intake agent
- Filter + deduplicate -> Normalisation/enrichment agent
- LLM classifier -> Verification agent
- Signal scorer -> Strategic implication agent
- Email/dashboard/Slack -> Presentation agent
- Orchestrator -> LangGraph or equivalent state machine

Do not jump to LangGraph before Day 1 works. The goal is not to look agentic; the goal is to make intelligence more reliable, inspectable, and useful.