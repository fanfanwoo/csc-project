"""
Validates the corroboration judge-match fixtures stay well-formed.

These are NEGATIVE cases for the future corroboration agent's judge-match step —
near-identical headlines that must NOT be treated as corroboration. The agent does
not exist yet; this test keeps the fixtures honest until it does.
"""
import json
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "corroboration_judge_cases.jsonl"

REQUIRED = {"case_id", "verdict", "held_signal", "reject_axes", "why_it_matters"}


def _cases():
    return [json.loads(line) for line in FIXTURE.read_text().splitlines() if line.strip()]


def test_fixture_present_and_nonempty():
    assert FIXTURE.exists()
    assert len(_cases()) >= 1


def test_each_case_well_formed():
    for case in _cases():
        assert REQUIRED <= set(case), f"{case.get('case_id')} missing keys"
        assert case["verdict"] == "must_reject_as_corroboration"
        # Two axes of non-corroboration, each a non-empty explanation.
        assert len(case["reject_axes"]) >= 2
        assert all(isinstance(a, str) and a.strip() for a in case["reject_axes"])
        sig = case["held_signal"]
        assert sig.get("canonical_url"), "held signal needs a URL to anchor the case"
        assert sig.get("title")
