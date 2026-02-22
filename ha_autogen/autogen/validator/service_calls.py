"""Service call validation — check service domain.name format and known domains."""

from __future__ import annotations

from typing import Any

from autogen.validator.models import ValidationIssue, ValidationSeverity

# Common HA service domains
KNOWN_DOMAINS = {
    "alarm_control_panel",
    "automation",
    "button",
    "camera",
    "climate",
    "counter",
    "cover",
    "fan",
    "homeassistant",
    "humidifier",
    "input_boolean",
    "input_button",
    "input_datetime",
    "input_number",
    "input_select",
    "input_text",
    "light",
    "lock",
    "media_player",
    "notify",
    "number",
    "remote",
    "scene",
    "script",
    "select",
    "siren",
    "switch",
    "timer",
    "tts",
    "vacuum",
    "water_heater",
    "zone",
}


def _extract_service_calls(obj: Any) -> list[str]:
    """Recursively extract all 'service' values from parsed YAML."""
    results: list[str] = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "service" and isinstance(value, str):
                results.append(value)
            else:
                results.extend(_extract_service_calls(value))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(_extract_service_calls(item))

    return results


def check_service_calls(parsed_yaml: dict) -> list[ValidationIssue]:
    """Validate service call format and domains.

    Returns warning-level issues for malformed service calls or unknown domains.
    """
    issues: list[ValidationIssue] = []
    services = _extract_service_calls(parsed_yaml)

    for service in services:
        if "." not in service:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.warning,
                    check_name="service_calls",
                    message=f"Malformed service call '{service}' — expected 'domain.action' format",
                )
            )
            continue

        domain = service.split(".", 1)[0]
        if domain not in KNOWN_DOMAINS:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.warning,
                    check_name="service_calls",
                    message=f"Unknown service domain '{domain}' in '{service}'",
                    suggestion=f"Common domains: light, switch, automation, climate, cover, media_player",
                )
            )

    return issues
