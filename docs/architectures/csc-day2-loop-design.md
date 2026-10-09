# CSC Day 2 — Agreed Loop Design

> Agreed 9 Oct 2026 after the loop design worksheet (Step 1 traces + 8 boxes) was reviewed against the reference design in [`csc-day2-v1b-loop-spec.md`](csc-day2-v1b-loop-spec.md).
> This doc is the **design of record** for the classify loop. Where it differs from the v1b spec, this doc wins. Where it says nothing, the v1b spec applies.

## What Step 1 showed

Five real classify traces from LangSmith:

| # | Source | Input | Confidence | Grounded quote? | Verdict | Failure kind |
|---|---|---|---|---|---|---|
| 1 | Kalkine (via Google News) | headline only | 0.4 | title only | unsure | **thin evidence** (loop can help) |
| 2 | ASIC Media | full body | 0.9 | yes | agree | none |
| 3 | ASIC Media | full body | 0.9 | yes | agree | none |
| 4 | ASIC Media (insider trading conviction) | full body | 0.9 | yes | disagree | **not relevant to the business** |
| 5 | Australian Broker (CBA AI ranking) | full body | 0.9 | yes | disagree | **wrong context**: CBA tagged as competitor |

**Conclusion:** the loop fixes thin evidence (#1) only. #4 and #5 were confident, grounded and still wrong. They would pass every check in the v1b evaluator, and retrying on the same input gives the same answer. They are a missing-context bug, not uncertainty, so they're fixed in the prompt, before the loop.

Confidence measures "did I read this article correctly?", not "does this matter to us?". Confidence is not truth.

## Changes from the v1b spec

### 0. Before the loop: business context in the classify prompt
Add to `csc/prompts/classifier_prompt.txt`:
- We are **Cars for CommBank**, an AU car and consumer-finance business inside CBA.
- **CBA is the home team.** CBA news is never `competitor_move` / `threat` from a competitor.
- Items outside AU car and consumer finance get a **low relevance_score**, however clear the article is.

Re-check traces #4 and #5 after this change, before building the loop.

### 1. Goal (adds "useful")
For each signal, produce a classification that is **correct, evidence-backed, and useful for the AU car and consumer-finance business**. If that isn't possible within budget, **say so visibly** in the brief rather than guessing.

### 2. State
As v1b (evidence list, attempts with eval reasons, actions used, tokens, status). Additionally record **elapsed time** per attempt.

### 3. Actions
As v1b, with one routing rule:
- **Aggregator items (Google News) skip `fetch_full_text`.** Their encoded redirect URLs aren't fetchable (see `csc/pipeline/evidence_state.py`), so the only moves are `fetch_related` or `flag_for_review`.
- **Empty body** is caught by code before the loop (see "Small fixes"), not spent on an LLM call.

### 4. Observation
After each `classify`: domain, signal type, confidence, evidence quote, tokens, **latency**.
After each fetch: **was new evidence actually added?** (a fetch can succeed and bring back the same text).
The rationale is logged for human review; code doesn't judge it.

### 5. Evaluator
Code checks, as v1b: schema valid, category allowed, confidence ≥ 0.7, **quote grounded**.

Required prompt change for the grounding check to work: `evidence_quote` must be an **exact quote** from the evidence text. Today the prompt allows "quote or paraphrase", and a paraphrase can't be checked by code.

Relevance is a judgement, not a code check. It's handled by the business context (change 0) and the existing human gate. No extra loop check for it in this version.

### 6. Retry
As v1b (each retry must **change the input**: more evidence, or error feedback), plus:
- **System errors stop, never retry.** Dead or invalid API key, quota exhausted, auth failure, or repeated network failure → stop the run and fail loudly. Only an *uncertain answer* earns a retry. (Lesson: 34 calls for 17 items on a dead key.)
- Every attempt is written to the trace log **before** the next action is chosen.

### 7. Stop conditions (whichever comes first)
v1b's five (passed, max 3 classify passes, token budget ~6k, no progress, flip-flop), plus:
- ⏱️ **time limit per item**: start at 60s, tune from traces.
- ⏱️ **time limit per run**: start at 20 min. Remaining items go to `needs_review` with reason `run_time_limit`. (Lesson: the 29 Sep run hung for nearly two hours.)
- 🛑 **system error** (see Retry): stops the whole run, not just the item.

### 8. Human gate
- **Where:** the 7am brief, in a "Needs your judgement" section with the evidence and the stop reason. Never silently dropped.
- **When:** any stop other than "passed"; plus v1b's extra gate (accepted, high impact, confidence < 0.8). Build on the existing review reasons in `csc/pipeline/verify.py` rather than a parallel mechanism.
- **A failed run must still reach the human.** If there is no brief, the gate doesn't exist. Run failure goes to the existing alert path (heartbeat / email). (Lesson: 6 Oct, an alarm that can't reach you isn't an alarm.)

## Small fixes the loop sits on (do first)
1. **Record what was fetched and what was dropped** (lesson 11), so every item's evidence and every filter decision is visible in the trace.
2. **"Every fetch failed" is a visible failure,** not an empty brief.

## Build order
1. Business context + exact-quote rule in the classify prompt → re-check traces #4, #5 and #1.
2. The two small fixes.
3. The loop (v1b skeleton + the changes above), with tracing built in.
4. Evals across runs as in v1b: 20 hand-labelled signals, Day 1 vs loop. Include #4 and #5 in the labelled set.
