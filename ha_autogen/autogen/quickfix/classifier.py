"""Classify review findings as Quick Fix or Guided Fix."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from autogen.reviewer.models import FindingCategory, ReviewFinding

SENSITIVE_DOMAINS = {"lock", "alarm_control_panel", "cover", "camera", "siren"}


class FixClassification(str, Enum):
    QUICK = "quick"
    GUIDED = "guided"


class EnrichedFinding(BaseModel):
    """A ReviewFinding extended with fix classification and pre-generated YAML."""

    finding: ReviewFinding
    fix_type: FixClassification
    fix_yaml: str | None = None
    requires_confirmation: bool = False
    fix_description: str = ""


# Categories eligible for deterministic Quick Fix
QUICK_FIX_CATEGORIES = {
    FindingCategory.deprecated_patterns,
    FindingCategory.card_type_recommendation,
    FindingCategory.inconsistent_cards,
}

# Categories that always need LLM / human judgment
GUIDED_FIX_CATEGORIES = {
    FindingCategory.security,
    FindingCategory.redundancy,
    FindingCategory.error_resilience,
    FindingCategory.layout_optimization,
    FindingCategory.missing_area_coverage,
    FindingCategory.unused_entities,
}


def _involves_sensitive_domain(
    finding: ReviewFinding,
    automation: dict | None = None,
) -> bool:
    """Check if the finding involves a security-sensitive domain."""
    # Check the title/description for sensitive domain names
    text = f"{finding.title} {finding.description}"
    for domain in SENSITIVE_DOMAINS:
        if domain in text:
            return True

    # Check automation actions if available
    if automation:
        actions = automation.get("action") or automation.get("actions") or []
        if isinstance(actions, dict):
            actions = [actions]
        for action in actions:
            if not isinstance(action, dict):
                continue
            service = action.get("service", "")
            if service.split(".")[0] in SENSITIVE_DOMAINS:
                return True
            # Check target entity IDs
            target = action.get("target", {}) or {}
            entity_ids = target.get("entity_id", [])
            if isinstance(entity_ids, str):
                entity_ids = [entity_ids]
            data = action.get("data", {}) or {}
            data_eids = data.get("entity_id", [])
            if isinstance(data_eids, str):
                data_eids = [data_eids]
            for eid in entity_ids + data_eids:
                if isinstance(eid, str) and eid.split(".")[0] in SENSITIVE_DOMAINS:
                    return True

    # Check current/suggested YAML strings
    for yaml_str in (finding.current_yaml, finding.suggested_yaml):
        if yaml_str:
            for domain in SENSITIVE_DOMAINS:
                if f"{domain}." in yaml_str:
                    return True

    return False


def classify(
    finding: ReviewFinding,
    automation: dict | None = None,
) -> EnrichedFinding:
    """Classify a single finding and determine fix type."""
    involves_sensitive = _involves_sensitive_domain(finding, automation)

    # Determine classification
    if finding.category in GUIDED_FIX_CATEGORIES:
        fix_type = FixClassification.GUIDED
    elif finding.category == FindingCategory.missing_guards and involves_sensitive:
        fix_type = FixClassification.GUIDED
    elif finding.category in QUICK_FIX_CATEGORIES:
        fix_type = FixClassification.QUICK
    elif finding.category == FindingCategory.missing_guards and not involves_sensitive:
        fix_type = FixClassification.QUICK
    elif finding.category == FindingCategory.trigger_efficiency:
        # Trigger efficiency is guided — requires understanding intended behavior
        fix_type = FixClassification.GUIDED
    else:
        fix_type = FixClassification.GUIDED

    # For quick fixes, use suggested_yaml if available
    fix_yaml = None
    fix_description = ""
    if fix_type == FixClassification.QUICK and finding.suggested_yaml:
        fix_yaml = finding.suggested_yaml
        fix_description = "Apply suggested fix from review analysis"

    # If classified as quick but no fix YAML available, downgrade to guided
    if fix_type == FixClassification.QUICK and fix_yaml is None:
        fix_type = FixClassification.GUIDED

    return EnrichedFinding(
        finding=finding,
        fix_type=fix_type,
        fix_yaml=fix_yaml,
        requires_confirmation=involves_sensitive,
        fix_description=fix_description,
    )


def classify_findings(
    findings: list[ReviewFinding],
    automations: list[dict] | None = None,
) -> list[EnrichedFinding]:
    """Classify a list of findings."""
    auto_map: dict[str, dict] = {}
    if automations:
        for a in automations:
            aid = a.get("id", "")
            if aid:
                auto_map[aid] = a

    return [
        classify(f, auto_map.get(f.automation_id))
        for f in findings
    ]
