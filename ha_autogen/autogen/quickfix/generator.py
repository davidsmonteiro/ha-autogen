"""Deterministic fix generators for Quick Fix findings."""

from __future__ import annotations

import copy
from io import StringIO

from ruamel.yaml import YAML

from autogen.quickfix.classifier import EnrichedFinding, FixClassification
from autogen.reviewer.models import FindingCategory, ReviewFinding

_yaml = YAML()
_yaml.default_flow_style = False


def _dump_yaml(data: dict | list) -> str:
    """Dump a dict/list to a YAML string."""
    buf = StringIO()
    _yaml.dump(data, buf)
    return buf.getvalue().rstrip()


def _get_action_list(automation: dict) -> list[dict]:
    """Normalize action/actions to a list of dicts."""
    actions = automation.get("action") or automation.get("actions") or []
    if isinstance(actions, dict):
        return [actions]
    if isinstance(actions, list):
        return [a for a in actions if isinstance(a, dict)]
    return []


def fix_deprecated_service(
    finding: ReviewFinding,
    automation: dict,
) -> tuple[str | None, str]:
    """Replace homeassistant.turn_on/off with domain-specific calls."""
    fixed = copy.deepcopy(automation)
    actions = _get_action_list(fixed)
    changed = False

    for action in actions:
        service = action.get("service", "")
        if service not in ("homeassistant.turn_on", "homeassistant.turn_off"):
            continue
        verb = "turn_on" if "turn_on" in service else "turn_off"

        # Determine target domain from entity_id
        target = action.get("target", {}) or {}
        entity_ids = target.get("entity_id", [])
        data = action.get("data", {}) or {}
        data_entity_ids = data.get("entity_id", [])
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]
        if isinstance(data_entity_ids, str):
            data_entity_ids = [data_entity_ids]
        all_ids = entity_ids + data_entity_ids

        if all_ids:
            domain = all_ids[0].split(".")[0] if "." in all_ids[0] else ""
            if domain:
                action["service"] = f"{domain}.{verb}"
                changed = True

    if not changed:
        return None, ""

    return (
        _dump_yaml(fixed),
        "Replaced generic homeassistant.turn_on/off with domain-specific calls",
    )


# Map of category → generator function
_GENERATORS: dict[
    FindingCategory,
    type[object]  # placeholder for typing
] = {}


def generate_fix(
    finding: ReviewFinding,
    automation: dict | None = None,
) -> tuple[str | None, str]:
    """Generate a deterministic fix for a finding.

    Returns (fix_yaml, description) or (None, "") if no fix can be generated.
    """
    if finding.category == FindingCategory.deprecated_patterns and automation:
        return fix_deprecated_service(finding, automation)

    # For other categories, fall back to suggested_yaml from review
    if finding.suggested_yaml:
        return finding.suggested_yaml, "Apply suggested fix from review analysis"

    return None, ""


def enrich_with_generated_fix(
    enriched: EnrichedFinding,
    automation: dict | None = None,
) -> EnrichedFinding:
    """Try to generate fix YAML for a Quick Fix that doesn't have one yet."""
    if enriched.fix_type != FixClassification.QUICK:
        return enriched
    if enriched.fix_yaml is not None:
        return enriched

    fix_yaml, fix_desc = generate_fix(enriched.finding, automation)
    if fix_yaml:
        enriched.fix_yaml = fix_yaml
        enriched.fix_description = fix_desc

    return enriched
