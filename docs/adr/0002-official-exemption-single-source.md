# 2. Exempt official full-body sources from single_source_high_impact

- **Status:** Accepted
- **Date:** 2026-06-26
- **Relates to:** ADR-0001 (verify gate routing) — refines the `single_source_high_impact` rule recorded there as a "known seam". Supersedes that seam's open question; does not change the rest of ADR-0001.
- **Context branch:** `day2-v1b-official-exemption` (Day 2 v1b, Phase 0)

## Context

ADR-0001 flagged `single_source_high_impact` (`duplicate_count == 0 and impact_score >= high_impact_threshold`) as the likely next over-holder once `large_inference_leap` was removed. The second live run confirmed it: 3 of 4 held items were full-body ASIC releases held solely on this rule.

With only two non-overlapping sources today (ASIC, Google News), `duplicate_count == 0` is the norm — so a high-impact ASIC item all but always trips the rule. But a full-body official regulator release is *strong* single-source evidence, not weak. Holding it hides exactly what the brief should surface.

## Decision

In `verify._reasons_for`, exempt an item from `single_source_high_impact` when it is **official AND full-body**:

```python
official_full_body = (
    ci.evidence_category == "official" and ci.evidence_level == "full_body"
)
if not official_full_body and ci.duplicate_count == 0 \
        and ci.impact_score >= high_impact_threshold:
    reasons.append("single_source_high_impact")
```

**Why `official + full_body`, not `official` alone.** The reason to trust ASIC single-source is the *full body*, not the label. If a two-stage official fetch fails or yields only a partial body, a high-impact single-source claim should still get a human look. The practical delta versus exempting on category alone is the **excerpt** case: a headline-only official item is already caught by `headline_only_high_impact`, so this change specifically routes **official + excerpt + high-impact + single-source** to review rather than passing it.

`evidence_category` / `evidence_level` are set by `evidence_state` (runs before classify before verify) and travel via dataclass inheritance, so they are reliably populated at the gate.

## Consequences

- Official full-body high-impact single-source items move from **held → passed** (marked if `sensitive_domain`). Official excerpt/headline items stay held. Non-official items are unaffected.
- `verify_items` logs `official_released` (count of items passing only because of this exemption) so the effect is confirmable on each run.
- Stakes are still surfaced: a high-stakes official item that now passes is flagged via `sensitive_domain` (marks-but-passes), so a human still sees it in the brief.
- This narrows but does not close the cross-source gap: the real fix for *non-official* single-source signals is a second independent source (v1b Phases 1–3) and, eventually, a corroboration agent — not loosening this rule further.
