"""Policy loader — proves every threshold PRD §6 cites resolves from the JSON, and
that policy is data (no value is hardcoded in the engine)."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.policy import Policy

# Every path PRD §6 references. The loader must resolve all of them — this is the
# contract that the engine reads keys, not literals.
CITED_PATHS = [
    "coverage.sum_insured_per_employee",
    "coverage.annual_opd_limit",
    "coverage.per_claim_limit",
    "coverage.family_floater.combined_limit",
    "opd_categories.consultation.sub_limit",
    "opd_categories.consultation.copay_percent",
    "opd_categories.consultation.network_discount_percent",
    "opd_categories.diagnostic.pre_auth_threshold",
    "opd_categories.diagnostic.high_value_tests_requiring_pre_auth",
    "opd_categories.dental.sub_limit",
    "opd_categories.alternative_medicine.max_sessions_per_year",
    "waiting_periods.initial_waiting_period_days",
    "waiting_periods.pre_existing_conditions_days",
    "waiting_periods.specific_conditions.diabetes",
    "document_requirements.CONSULTATION.required",
    "document_requirements.DIAGNOSTIC.required",
    "fraud_thresholds.same_day_claims_limit",
    "fraud_thresholds.monthly_claims_limit",
    "fraud_thresholds.high_value_claim_threshold",
    "fraud_thresholds.auto_manual_review_above",
    "fraud_thresholds.fraud_score_manual_review_threshold",
    "network_hospitals",
    "submission_rules.minimum_claim_amount",
    "submission_rules.deadline_days_from_treatment",
    "exclusions.conditions",
]


@pytest.fixture
def policy() -> Policy:
    return Policy.from_file(get_settings().policy_path)


def test_every_cited_path_resolves(policy: Policy):
    for path in CITED_PATHS:
        assert policy.get(path) is not None, f"policy path did not resolve: {path}"


def test_missing_path_raises_loud(policy: Policy):
    with pytest.raises(KeyError):
        policy.get("coverage.does_not_exist")
    assert policy.get("coverage.does_not_exist", None) is None  # default suppresses


def test_named_accessors_match_raw_paths(policy: Policy):
    assert policy.per_claim_limit() == policy.get("coverage.per_claim_limit")
    assert policy.category("CONSULTATION") == policy.get("opd_categories.consultation")
    assert policy.required_documents("consultation") == ["PRESCRIPTION", "HOSPITAL_BILL"]
    assert policy.waiting_period_days("diabetes") == 90
    assert policy.waiting_period_days("unknown_condition") is None
    assert policy.min_claim_amount() == 500


def test_member_and_dependent_resolution(policy: Policy):
    emp = policy.member("EMP001")
    assert emp is not None and emp["name"] == "Rajesh Kumar"
    assert emp["dependents"] == ["DEP001", "DEP002"]
    assert policy.member("DEP002")["name"] == "Arjun Kumar"
    assert policy.member("NOPE") is None
    assert policy.member(None) is None


def test_network_hospital_match_is_case_insensitive(policy: Policy):
    assert policy.is_network_hospital("Apollo Hospitals")
    assert policy.is_network_hospital("apollo hospitals  ")
    assert not policy.is_network_hospital("City Clinic, Bengaluru")
    assert not policy.is_network_hospital(None)
