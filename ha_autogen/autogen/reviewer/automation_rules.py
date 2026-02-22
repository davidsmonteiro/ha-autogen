"""Deterministic rules for automation review — no LLM, fast, always run."""

from __future__ import annotations

from io import StringIO

from ruamel.yaml import YAML

from autogen.reviewer.models import (
    FindingCategory,
    FindingSeverity,
    ReviewFinding,
)

_yaml = YAML()
_yaml.default_flow_style = False

SENSITIVE_DOMAINS = {"lock", "alarm_control_panel", "cover", "camera", "siren"}


def _dump_yaml(data: dict) -> str:
    """Dump a dict to a YAML string."""
    buf = StringIO()
    _yaml.dump(data, buf)
    return buf.getvalue().rstrip()


def _get_trigger_list(automation: dict) -> list[dict]:
    """Normalize trigger / triggers field to a list of dicts."""
    triggers = automation.get("trigger") or automation.get("triggers") or []
    if isinstance(triggers, dict):
        return [triggers]
    if isinstance(triggers, list):
        return [t for t in triggers if isinstance(t, dict)]
    return []


def _get_condition_list(automation: dict) -> list[dict]:
    """Normalize condition / conditions field to a list."""
    conditions = automation.get("condition") or automation.get("conditions") or []
    if isinstance(conditions, dict):
        return [conditions]
    if isinstance(conditions, list):
        return list(conditions)
    return []


def _get_action_list(automation: dict) -> list[dict]:
    """Normalize action / actions field to a list of dicts."""
    actions = automation.get("action") or automation.get("actions") or []
    if isinstance(actions, dict):
        return [actions]
    if isinstance(actions, list):
        return [a for a in actions if isinstance(a, dict)]
    return []


def _auto_id(automation: dict) -> str:
    return automation.get("id", "unknown")


def _auto_alias(automation: dict) -> str:
    return automation.get("alias", "Unnamed automation")


def check_trigger_efficiency(automation: dict) -> list[ReviewFinding]:
    """Flag time_pattern triggers that fire very frequently."""
    findings: list[ReviewFinding] = []
    for trigger in _get_trigger_list(automation):
        platform = trigger.get("platform", "")
        if platform == "time_pattern":
            seconds = trigger.get("seconds")
            minutes = trigger.get("minutes")
            # Flag if polling every second or every minute
            if seconds is not None or (minutes is not None and str(minutes).startswith("/")):
                findings.append(
                    ReviewFinding(
                        severity=FindingSeverity.warning,
                        category=FindingCategory.trigger_efficiency,
                        automation_id=_auto_id(automation),
                        automation_alias=_auto_alias(automation),
                        title="Frequent time_pattern trigger",
                        description=(
                            "This automation uses a time_pattern trigger that fires frequently. "
                            "Consider using a state-based trigger or increasing the interval."
                        ),
                    )
                )
    return findings


def check_missing_guards(automation: dict) -> list[ReviewFinding]:
    """Flag automations with triggers but no conditions."""
    findings: list[ReviewFinding] = []
    triggers = _get_trigger_list(automation)
    conditions = _get_condition_list(automation)

    if triggers and not conditions:
        findings.append(
            ReviewFinding(
                severity=FindingSeverity.suggestion,
                category=FindingCategory.missing_guards,
                automation_id=_auto_id(automation),
                automation_alias=_auto_alias(automation),
                title="No conditions defined",
                description=(
                    "This automation has triggers but no conditions. "
                    "Consider adding conditions to prevent unintended activations."
                ),
            )
        )
    return findings


def check_security_concerns(automation: dict) -> list[ReviewFinding]:
    """Flag sensitive domains used without conditions."""
    findings: list[ReviewFinding] = []
    conditions = _get_condition_list(automation)

    for action in _get_action_list(automation):
        service = action.get("service", "")
        # Extract domain from service call (e.g. "lock.lock" → "lock")
        domain = service.split(".")[0] if "." in service else ""

        # Also check entity_id targets
        target = action.get("target", {}) or {}
        entity_ids = target.get("entity_id", [])
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]

        # Check data.entity_id too (older format)
        data = action.get("data", {}) or {}
        data_entity_ids = data.get("entity_id", [])
        if isinstance(data_entity_ids, str):
            data_entity_ids = [data_entity_ids]
        entity_ids.extend(data_entity_ids)

        # Collect all domains involved
        domains_involved = set()
        if domain:
            domains_involved.add(domain)
        for eid in entity_ids:
            if "." in eid:
                domains_involved.add(eid.split(".")[0])

        sensitive_found = domains_involved & SENSITIVE_DOMAINS
        if sensitive_found:
            severity = FindingSeverity.critical if not conditions else FindingSeverity.warning
            desc = (
                f"This automation controls sensitive domain(s): {', '.join(sorted(sensitive_found))}. "
            )
            if not conditions:
                desc += "It has NO conditions, meaning the action runs unconditionally."
            else:
                desc += "Verify that conditions are sufficient to prevent unauthorized activation."

            findings.append(
                ReviewFinding(
                    severity=severity,
                    category=FindingCategory.security,
                    automation_id=_auto_id(automation),
                    automation_alias=_auto_alias(automation),
                    title=f"Sensitive domain without adequate guards: {', '.join(sorted(sensitive_found))}",
                    description=desc,
                )
            )
    return findings


def check_deprecated_patterns(automation: dict) -> list[ReviewFinding]:
    """Flag homeassistant.turn_on/off — suggest domain-specific calls."""
    findings: list[ReviewFinding] = []
    for action in _get_action_list(automation):
        service = action.get("service", "")
        if service in ("homeassistant.turn_on", "homeassistant.turn_off"):
            verb = "turn_on" if "turn_on" in service else "turn_off"
            # Try to suggest domain-specific service
            target = action.get("target", {}) or {}
            entity_ids = target.get("entity_id", [])
            data = action.get("data", {}) or {}
            data_entity_ids = data.get("entity_id", [])
            if isinstance(entity_ids, str):
                entity_ids = [entity_ids]
            if isinstance(data_entity_ids, str):
                data_entity_ids = [data_entity_ids]
            all_ids = entity_ids + data_entity_ids

            suggestion = ""
            if all_ids:
                domain = all_ids[0].split(".")[0] if "." in all_ids[0] else ""
                if domain:
                    suggestion = f" Use `{domain}.{verb}` instead."

            findings.append(
                ReviewFinding(
                    severity=FindingSeverity.suggestion,
                    category=FindingCategory.deprecated_patterns,
                    automation_id=_auto_id(automation),
                    automation_alias=_auto_alias(automation),
                    title=f"Generic {service} call",
                    description=(
                        f"`{service}` is a generic call. "
                        f"Domain-specific services are preferred for clarity and reliability."
                        f"{suggestion}"
                    ),
                )
            )
    return findings


def run_all_rules(automation: dict) -> list[ReviewFinding]:
    """Run all deterministic rules on a single automation."""
    findings: list[ReviewFinding] = []
    findings.extend(check_trigger_efficiency(automation))
    findings.extend(check_missing_guards(automation))
    findings.extend(check_security_concerns(automation))
    findings.extend(check_deprecated_patterns(automation))
    return findings
