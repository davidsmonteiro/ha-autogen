"""Tests for quickfix classifier."""

from __future__ import annotations

from autogen.quickfix.classifier import (
    EnrichedFinding,
    FixClassification,
    classify,
    classify_findings,
    _involves_sensitive_domain,
)
from autogen.reviewer.models import FindingCategory, FindingSeverity, ReviewFinding


def _finding(
    category: FindingCategory = FindingCategory.deprecated_patterns,
    severity: FindingSeverity = FindingSeverity.suggestion,
    title: str = "Test finding",
    description: str = "Test description",
    suggested_yaml: str | None = None,
    current_yaml: str | None = None,
    automation_id: str = "auto_1",
    finding_id: str = "f1",
) -> ReviewFinding:
    return ReviewFinding(
        finding_id=finding_id,
        severity=severity,
        category=category,
        automation_id=automation_id,
        title=title,
        description=description,
        suggested_yaml=suggested_yaml,
        current_yaml=current_yaml,
    )


class TestInvolvesSensitiveDomain:
    def test_lock_in_title(self) -> None:
        f = _finding(title="Sensitive domain without adequate guards: lock")
        assert _involves_sensitive_domain(f) is True

    def test_alarm_in_description(self) -> None:
        f = _finding(description="Controls alarm_control_panel.home_alarm")
        assert _involves_sensitive_domain(f) is True

    def test_no_sensitive_domain(self) -> None:
        f = _finding(title="Generic turn_on call", description="Uses light.living_room")
        assert _involves_sensitive_domain(f) is False

    def test_sensitive_in_current_yaml(self) -> None:
        f = _finding(current_yaml="service: lock.lock\ntarget:\n  entity_id: lock.front_door")
        assert _involves_sensitive_domain(f) is True

    def test_sensitive_in_automation_actions(self) -> None:
        f = _finding()
        auto = {
            "id": "auto_1",
            "action": [{"service": "cover.open_cover", "target": {"entity_id": "cover.garage"}}],
        }
        assert _involves_sensitive_domain(f, auto) is True

    def test_sensitive_in_entity_id(self) -> None:
        f = _finding()
        auto = {
            "id": "auto_1",
            "action": [{"service": "homeassistant.turn_on", "data": {"entity_id": "camera.front"}}],
        }
        assert _involves_sensitive_domain(f, auto) is True

    def test_not_sensitive_automation(self) -> None:
        f = _finding()
        auto = {
            "id": "auto_1",
            "action": [{"service": "light.turn_on", "target": {"entity_id": "light.living"}}],
        }
        assert _involves_sensitive_domain(f, auto) is False


class TestClassify:
    def test_deprecated_patterns_with_yaml_is_quick(self) -> None:
        f = _finding(
            category=FindingCategory.deprecated_patterns,
            suggested_yaml="service: light.turn_on",
        )
        enriched = classify(f)
        assert enriched.fix_type == FixClassification.QUICK
        assert enriched.fix_yaml == "service: light.turn_on"

    def test_deprecated_patterns_without_yaml_becomes_guided(self) -> None:
        f = _finding(category=FindingCategory.deprecated_patterns, suggested_yaml=None)
        enriched = classify(f)
        assert enriched.fix_type == FixClassification.GUIDED

    def test_security_is_always_guided(self) -> None:
        f = _finding(category=FindingCategory.security, suggested_yaml="fix: something")
        enriched = classify(f)
        assert enriched.fix_type == FixClassification.GUIDED

    def test_redundancy_is_guided(self) -> None:
        f = _finding(category=FindingCategory.redundancy)
        enriched = classify(f)
        assert enriched.fix_type == FixClassification.GUIDED

    def test_missing_guards_non_sensitive_with_yaml_is_quick(self) -> None:
        f = _finding(
            category=FindingCategory.missing_guards,
            title="No conditions defined",
            description="Light automation has no conditions",
            suggested_yaml="condition:\n  - platform: state",
        )
        enriched = classify(f)
        assert enriched.fix_type == FixClassification.QUICK

    def test_missing_guards_sensitive_is_guided(self) -> None:
        f = _finding(
            category=FindingCategory.missing_guards,
            title="No conditions defined",
            description="lock automation has no conditions",
        )
        enriched = classify(f)
        assert enriched.fix_type == FixClassification.GUIDED

    def test_card_type_recommendation_with_yaml_is_quick(self) -> None:
        f = _finding(
            category=FindingCategory.card_type_recommendation,
            suggested_yaml="type: gauge",
        )
        enriched = classify(f)
        assert enriched.fix_type == FixClassification.QUICK

    def test_trigger_efficiency_is_guided(self) -> None:
        f = _finding(category=FindingCategory.trigger_efficiency)
        enriched = classify(f)
        assert enriched.fix_type == FixClassification.GUIDED

    def test_sensitive_quick_fix_requires_confirmation(self) -> None:
        f = _finding(
            category=FindingCategory.deprecated_patterns,
            title="Generic homeassistant.turn_on for lock",
            suggested_yaml="service: lock.lock",
        )
        enriched = classify(f)
        assert enriched.requires_confirmation is True


class TestClassifyFindings:
    def test_classify_list(self) -> None:
        findings = [
            _finding(
                category=FindingCategory.deprecated_patterns,
                suggested_yaml="fix",
                automation_id="a1",
                finding_id="f1",
            ),
            _finding(
                category=FindingCategory.security,
                automation_id="a2",
                finding_id="f2",
            ),
        ]
        automations = [{"id": "a1"}, {"id": "a2"}]
        enriched = classify_findings(findings, automations)
        assert len(enriched) == 2
        assert enriched[0].fix_type == FixClassification.QUICK
        assert enriched[1].fix_type == FixClassification.GUIDED

    def test_classify_without_automations(self) -> None:
        findings = [_finding(category=FindingCategory.deprecated_patterns, suggested_yaml="fix")]
        enriched = classify_findings(findings)
        assert len(enriched) == 1
