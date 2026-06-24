# Verify gate routes signals into pass / hold deterministically

**Status:** accepted (Day 2 v1a, 2026-06-24)

Between classify and score, a verify gate (`csc/pipeline/verify.py`) partitions
classified items into a **pass** stream (→ score → brief) and a **hold** stream
(→ human review queue). Routing is decided in code, never by the LLM, so the same
input always routes the same way and the rules are auditable.

## The decisions worth recording

**Reliability flags hold; the stakes flag only marks.** Four reliability reasons
pull an item out of the brief into the review queue — `low_confidence`,
`single_source_high_impact`, `large_inference_leap`, and `headline_only_high_impact`.
The stakes reason `sensitive_domain` (regulatory/legal/compliance/lending/privacy/
liability keywords) deliberately does **not** hold: a well-evidenced sensitive item
is surfaced in the brief *with* a visible flag, not hidden in a queue. Hiding strong
sensitive signals would defeat the point of surfacing them.

**`headline_only_high_impact` is new in v1a.** A Google-News-only story carries no
fetchable article body (see ADR context: the encoded `/rss/articles/…` links resolve
back to Google's own app, not the publisher). It therefore cannot become a
high-impact *top signal* on a headline alone — if `evidence_level == "headline_only"`
and impact ≥ threshold, it holds for a human. This keys on the `evidence_level`
label set by `evidence_state`, not on the source name.

**One named threshold, reused.** `verify.high_impact_threshold` (pipeline.yaml,
default 0.8) is a single named config value shared by both high-impact rules
(`single_source_high_impact` and `headline_only_high_impact`) — not a hardcoded
duplicate. Tune the gate in one place.

## Consequence to watch

Official single-source items with impact ≥ 0.8 (e.g. an ASIC release with no
corroborating duplicate) route to **hold**, not the brief, via
`single_source_high_impact`. This is the rule working as designed, but if official
single-source items should pass, that is a v1b tuning decision — revisit the rule
or exempt the `official` evidence_category, rather than treating it as a bug.
