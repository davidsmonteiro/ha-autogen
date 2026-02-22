"""Tests for quickfix fix generators."""

from __future__ import annotations

from autogen.quickfix.classifier import EnrichedFinding, FixClassification
from autogen.quickfix.generator import (
    enrich_with_generated_fix,
    fix_deprecated_service,
    generate_fix,
)
from autogen.reviewer.models import FindingCategory, FindingSeverity, ReviewFinding


def _finding(
    category: FindingCategory = FindingCategory.deprecated_patterns,
    suggested_yaml: str | None = None,
    **kwargs,
) -> ReviewFinding:
    return ReviewFinding(
        severity=FindingSeverity.suggestion,
        category=category,
        title=kwargs.pop("title", "Test"),
        description=kwargs.pop("description", "Desc"),
        suggested_yaml=suggested_yaml,
        **kwargs,
    )


class TestFixDeprecatedService:
    def test_replaces_turn_on(self) -> None:
        auto = {
            "id": "test_auto",
            "action": [
                {"service": "homeassistant.turn_on", "target": {"entity_id": "light.living_room"}},
            ],
        }
        finding = _finding()
        fix_yaml, desc = fix_deprecated_service(finding, auto)
        assert fix_yaml is not None
        assert "light.turn_on" in fix_yaml
        assert "homeassistant.turn_on" not in fix_yaml
        assert "Replaced" in desc

    def test_replaces_turn_off(self) -> None:
        auto = {
            "id": "test_auto",
            "action": [
                {"service": "homeassistant.turn_off", "data": {"entity_id": "switch.fan"}},
            ],
        }
        finding = _finding()
        fix_yaml, desc = fix_deprecated_service(finding, auto)
        assert fix_yaml is not None
        assert "switch.turn_off" in fix_yaml

    def test_no_change_when_not_deprecated(self) -> None:
        auto = {
            "id": "test_auto",
            "action": [{"service": "light.turn_on", "target": {"entity_id": "light.living"}}],
        }
        finding = _finding()
        fix_yaml, desc = fix_deprecated_service(finding, auto)
        assert fix_yaml is None
        assert desc == ""

    def test_handles_no_entity_ids(self) -> None:
        auto = {
            "id": "test_auto",
            "action": [{"service": "homeassistant.turn_on"}],
        }
        finding = _finding()
        fix_yaml, desc = fix_deprecated_service(finding, auto)
        assert fix_yaml is None  # Can't determine domain

    def test_multiple_actions_only_fixes_deprecated(self) -> None:
        auto = {
            "id": "test_auto",
            "action": [
                {"service": "homeassistant.turn_on", "target": {"entity_id": "light.living"}},
                {"service": "light.turn_off", "target": {"entity_id": "light.kitchen"}},
            ],
        }
        finding = _finding()
        fix_yaml, desc = fix_deprecated_service(finding, auto)
        assert fix_yaml is not None
        assert "light.turn_on" in fix_yaml
        assert "light.turn_off" in fix_yaml  # unchanged action preserved

    def test_handles_actions_key(self) -> None:
        """Test with 'actions' (plural) key."""
        auto = {
            "id": "test_auto",
            "actions": [
                {"service": "homeassistant.turn_on", "target": {"entity_id": "light.x"}},
            ],
        }
        finding = _finding()
        fix_yaml, desc = fix_deprecated_service(finding, auto)
        # The function reads 'action' first, then 'actions'
        assert fix_yaml is not None
        assert "light.turn_on" in fix_yaml


class TestGenerateFix:
    def test_deprecated_patterns_with_automation(self) -> None:
        finding = _finding(category=FindingCategory.deprecated_patterns)
        auto = {
            "id": "a1",
            "action": [{"service": "homeassistant.turn_on", "target": {"entity_id": "light.x"}}],
        }
        fix_yaml, desc = generate_fix(finding, auto)
        assert fix_yaml is not None

    def test_deprecated_patterns_without_automation(self) -> None:
        finding = _finding(category=FindingCategory.deprecated_patterns)
        fix_yaml, desc = generate_fix(finding, None)
        assert fix_yaml is None

    def test_fallback_to_suggested_yaml(self) -> None:
        finding = _finding(
            category=FindingCategory.inconsistent_cards,
            suggested_yaml="type: entities\n",
        )
        fix_yaml, desc = generate_fix(finding)
        assert fix_yaml == "type: entities\n"

    def test_no_fix_available(self) -> None:
        finding = _finding(category=FindingCategory.security)
        fix_yaml, desc = generate_fix(finding)
        assert fix_yaml is None
        assert desc == ""


class TestEnrichWithGeneratedFix:
    def test_enriches_quick_fix_without_yaml(self) -> None:
        finding = _finding(category=FindingCategory.deprecated_patterns)
        enriched = EnrichedFinding(
            finding=finding,
            fix_type=FixClassification.QUICK,
            fix_yaml=None,
        )
        auto = {
            "id": "a1",
            "action": [{"service": "homeassistant.turn_on", "target": {"entity_id": "light.x"}}],
        }
        result = enrich_with_generated_fix(enriched, auto)
        assert result.fix_yaml is not None
        assert "light.turn_on" in result.fix_yaml

    def test_skips_guided_fixes(self) -> None:
        finding = _finding(category=FindingCategory.security)
        enriched = EnrichedFinding(
            finding=finding,
            fix_type=FixClassification.GUIDED,
        )
        result = enrich_with_generated_fix(enriched)
        assert result.fix_yaml is None

    def test_preserves_existing_fix_yaml(self) -> None:
        finding = _finding(category=FindingCategory.deprecated_patterns)
        enriched = EnrichedFinding(
            finding=finding,
            fix_type=FixClassification.QUICK,
            fix_yaml="existing: yaml",
        )
        result = enrich_with_generated_fix(enriched)
        assert result.fix_yaml == "existing: yaml"
