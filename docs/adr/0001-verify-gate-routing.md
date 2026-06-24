# 1. Verify gate routing policy

- **Status:** Accepted
- **Date:** 2026-06-24
- **Amended:** 2026-06-24 (pre-merge) — `large_inference_leap` removed from the gate after the first real run showed it was a broken proxy. See Decision and Consequences. (Amended in place rather than superseded because neither this ADR nor the v1a code had merged yet.)
- **Context branch / commit:** `day2-v1a-verify` @ `d9b03d8` (Day 2 v1a, Phase 2b)
- **Supersedes / relates to:** Day 2 v1a build spec (`docs/architectures/csc-day2-v1a-spec.md` — design intent, not live state)

## Context

After classification, CSC needs to decide which signals reach the brief and which are withheld for a human. The Day 1 design only *labelled* items with a `human_review_flag` string; everything still flowed to the scorer and into the brief. We needed actual routing so weak evidence cannot become strong intelligence.

A key constraint shaped this: Google News items carry no fetchable article body (the connector sets `canonical_url = None`, stores a raw redirect, and the body is only an RSS headline snippet), while ASIC carries full bodies. So evidence quality varies by source and must influence routing. This is why `evidence_state` stamps an `evidence_level` (`full_body` / `excerpt` / `headline_only`) onto every item before classification.

We explicitly did **not** introduce a state machine or agent framework here — the gate only partitions; it does not choose-then-loop. (See the "no state machine" rationale; a state machine earns its place only when a loop-back cycle exists, which v1a has none.)

## Decision

The verify stage (`csc/pipeline/verify.py`) partitions classified items into a **pass stream** (→ score → brief) and a **hold stream** (→ human review queue, persisted to `data/review/{run_id}.jsonl` and surfaced in a brief section). Held items do not reach the scorer. Routing is fully deterministic, in code; the LLM does not decide it.

Review reasons split into two kinds that route differently:

**Reliability flags → HOLD** (the item may not be real or accurate; keep it out of the brief):
- `low_confidence` — `confidence < confidence_floor`
- `single_source_high_impact` — `duplicate_count == 0 and impact_score >= high_impact_threshold`
- `headline_only_high_impact` — `evidence_level == "headline_only" and impact_score >= high_impact_threshold`

> **Removed in v1a:** `large_inference_leap` (`inference_note` > 200 chars) was part of the original gate but is **not** in the shipped v1a. The first real run showed it was a broken proxy — see Consequences. A proper inference-leap measure is deferred to v1b.

**Stakes flag → MARK but PASS** (the item is high-stakes regardless of certainty; surface it *with* a flag, do not hide it):
- `sensitive_domain` — title/rationale contains regulatory / legal / compliance / lending / privacy / liability

### The three non-obvious decisions, with rationale

1. **`headline_only_high_impact` must hold.** A Google-News-only story has no fetchable body — its impact is inferred from a headline alone. Allowing a headline to mint a high-impact top signal would let the thinnest evidence drive the strongest claim, the exact failure the evidence-as-state design exists to prevent. Holding it routes a human to find a real source before it counts as intelligence. Google News is a discovery source, not an evidence source.

2. **`sensitive_domain` marks but does not hold, unlike the reliability flags.** Reliability flags answer "is this trustworthy?" — a no means withhold. `sensitive_domain` answers "is this high-stakes?" — which is orthogonal to trust. A well-evidenced lending/privacy item is exactly what the brief should surface; hiding it would be the wrong outcome. So it sets the visible flag and stays in the pass stream. This hold-vs-mark distinction is what makes verify a *router* rather than a *filter*.

3. **One shared named threshold.** `verify.high_impact_threshold` (default `0.8`) lives in `pipeline.yaml` and drives *both* high-impact rules (`single_source_high_impact` and `headline_only_high_impact`). A single named knob avoids a hardcoded duplicate drifting out of sync and gives one place to tune "what counts as high impact."

## Consequences

- Weak evidence (low confidence, lone high-impact claims, headline-only big claims) is withheld from the brief and queued for a human, with reasons attached.
- High-stakes-but-trustworthy items still reach the brief, flagged.
- `evidence_level` from `evidence_state` is now load-bearing for routing, not just metadata.
- **`large_inference_leap` removed (first-run finding, 2026-06-24).** The first real run (20 items) held 17, and all 17 tripped `large_inference_leap`; observed `inference_note` lengths were 210–447 chars — entirely above the 200 threshold. The rule was measuring *verbosity* (whether the classifier wrote a note at all), not inference-leap size, and was swamping the deliberate reliability/high-impact logic. Character count is a broken proxy for leap size and was removed for v1a. The right design — leap *relative to evidence* (e.g. inference vs. rationale/body) — is deferred to v1b, where it also needs more than one run to calibrate and must handle headline-only items that have no body to ratio against. (The threshold was also never in config, unlike `high_impact_threshold` — another reason not to merely re-tune it.)
- **Known seam (deferred to v1b):** `single_source_high_impact` fires on *any* single high-impact source, including ASIC — an official, full-body, primary regulator document, which is strong evidence, not weak. With only two non-overlapping sources today, `duplicate_count == 0` is the norm, so this rule leans almost entirely on `impact_score >= threshold` and is the most likely *next* over-holder once `large_inference_leap` is gone. v1a holds these as specified. The likely v1b refinement is to gate the rule on `evidence_category != "official"`, relying on `sensitive_domain` to surface official high-impact items marked-but-passed. Confirm against run data before changing; a separate ADR will record it.
