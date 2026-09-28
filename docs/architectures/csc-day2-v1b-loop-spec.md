# CSC Day 2 — First Loop Spec: Evidence-Sufficiency Loop

> **Do this first:** cover everything below "Reference design" and draw your own version of the 8 boxes (Goal, State, Action, Observation, Evaluator, Retry, Stop, Human gate). Then compare. Where yours differs, decide which is better and why. That comparison *is* the lesson.

## Where the loop goes
Day 1 pipeline (unchanged except one step):

```
Scheduler → Source → Filter → Dedupe → [LLM classify ⟲ LOOP] → Score → Summarise → Brief
```

**Why here and only here:** everything before classification is deterministic. It doesn't need to observe and adjust. Classification is the first step where the right next move depends on what happened (e.g. an RSS snippet was too thin to classify). Scoring and summarising depend on classification quality, so fixing it here pays off downstream.

**Why not elsewhere (yet):** looping the summariser adds cost without clear value until classification is reliable. Keep it deterministic.

---

## Reference design

### 1. GOAL
For each signal, produce a classification that is **correct, evidence-backed and confident enough to score**. If that isn't possible within budget, **say so visibly** rather than guessing.

### 2. STATE (one record per signal, carried through the loop)
```python
{
  "signal_id": "...",
  "evidence": [ {"source": "rss_snippet", "text": "..."} ],  # grows each pass
  "attempts": [                                              # one per pass
     {"pass": 1, "action": "classify", "category": "...",
      "confidence": 0.55, "evidence_quote": "...",
      "eval": {"passed": False, "reasons": ["quote_not_found"]}}
  ],
  "actions_used": ["classify"],
  "tokens_used": 1840,
  "status": "in_progress"   # → accepted | needs_review
}
```
This follows your working rules: evidence travels with the signal, and raw and intermediate records are kept.

### 3. ACTIONS (a small, named set)
| Action | What it does | Cost |
|---|---|---|
| `classify` | LLM classifies using current evidence; must return category, confidence, and an **exact quote** supporting it | 1 LLM call |
| `fetch_full_text` | Replace the RSS snippet with the full article text | network, no LLM |
| `fetch_related` | Find 1 related source on the same entity/event | network, no LLM |
| `flag_for_review` | Hand to human (terminal) | none |

### 4. OBSERVATION
After each `classify`: category, confidence, evidence quote, tokens used.
After each fetch: whether new evidence was actually added (it may fail or duplicate).

### 5. EVALUATOR (inside the loop, run every pass)
Mostly **deterministic checks**, because self-reported confidence is not truth:

| Check | Type | Fails when |
|---|---|---|
| Schema valid | code | missing fields / bad types |
| Category allowed | code | not in the taxonomy (market, policy, auto/EV, consumer finance, competitors, AI) |
| **Quote grounded** | code | the evidence quote does not appear in the evidence text (catches made-up evidence) |
| Confidence ≥ 0.7 | threshold | below the bar |

`passed = all checks true`. The eval records **reasons**, and the retry logic uses them.

### 6. RETRY (targeted; not just "try again")
```
if passed                              → accept
elif "quote_not_found" or low confidence:
    if full text not yet fetched       → fetch_full_text, then classify
    elif related not yet fetched       → fetch_related, then classify
    else                               → human gate
elif schema/category invalid           → classify once more with the error message included
```
Each retry **changes the input** (more evidence, or error feedback). Retrying on an identical input is how loops go back and forth.

### 7. STOP CONDITIONS (whichever comes first)
- ✅ evaluator passes → `accepted`
- 🔢 max **3 classify passes**
- 💰 token budget per signal exceeded (start at ~6k; tune from traces)
- 📉 no progress: two passes return the same category and confidence changes by < 0.05
- 🔁 back-and-forth: category flips A → B → A

### 8. HUMAN GATE
- Any stop other than ✅ → `needs_review`. It **appears in the brief** in a "Needs your judgement" section with the evidence and the reasons. Never silently dropped.
- Extra gate: `accepted` **but** scored high-impact **and** confidence < 0.8 → also shown for review. The cost of being wrong scales with impact.

---

## Tracing (build this with the loop, not after)
Append one JSONL line per pass to `traces/YYYY-MM-DD.jsonl`:
```json
{"signal_id":"…","pass":2,"action":"fetch_full_text","eval":{"passed":true,"reasons":[]},"decision":"accept","why":"quote grounded, conf 0.82","tokens":2310}
```
After each run, read 5 traces. Ask yourself: did the loop do what I would have done?

## Loop skeleton (for Claude Code to fill in)
```python
def classify_with_loop(signal, max_passes=3, token_budget=6000):
    state = init_state(signal)
    while True:
        result = classify(state)                 # action
        verdict = evaluate(result, state)         # evaluator
        record(state, result, verdict)            # state + trace
        stop, status, why = should_stop(state, verdict, max_passes, token_budget)
        if stop:
            state["status"] = status              # accepted | needs_review
            log_trace(state, why)
            return state
        next_action = choose_retry(state, verdict)   # targeted retry
        apply(next_action, state)                     # fetch_full_text / fetch_related
```
Keep these as functions (Day 1 rule: functions before classes).

## Evals across runs (does the loop beat Day 1?)
1. Hand-label **20 real signals** (correct category), including some thin RSS snippets.
2. Run Day 1 (single classify) vs Day 2 (loop). Compare:
   - accuracy vs your labels
   - % `needs_review`
   - average tokens per signal
3. The loop is worth keeping only if accuracy goes up at an acceptable cost, and `needs_review` catches the cases that are actually hard.

## Done when
- [ ] Loop runs on ~20 real signals
- [ ] Traces show ≥ 1 retry and ≥ 1 `needs_review`
- [ ] You can explain why every run stopped
- [ ] Evals across runs show improvement over Day 1 (or a clear, written reason why not)

## Reflection (5 min, after the run)
1. Which stop condition fired most? What does that say about your sources?
2. Did any "accepted" signal look wrong to you? What check would have caught it?
3. What would you change before carrying this pattern into CDC?
