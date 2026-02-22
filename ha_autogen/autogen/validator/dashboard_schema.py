"""Dashboard-specific validation checks for Lovelace YAML."""

from __future__ import annotations

from typing import Any

from autogen.validator.models import ValidationIssue, ValidationSeverity

VALID_CARD_TYPES = {
    "entities",
    "gauge",
    "glance",
    "history-graph",
    "horizontal-stack",
    "vertical-stack",
    "media-control",
    "thermostat",
    "weather-forecast",
    "picture-entity",
    "button",
    "light",
    "markdown",
    "map",
    "conditional",
    "grid",
    "statistics-graph",
    "logbook",
    "calendar",
    "energy-date-selection",
    "energy-usage-graph",
    "alarm-panel",
    "humidifier",
    "sensor",
    "tile",
    "area",
    "heading",
    "sections",
}

# Required fields per card type (beyond 'type')
CARD_REQUIRED_FIELDS: dict[str, list[str]] = {
    "gauge": ["entity"],
    "thermostat": ["entity"],
    "media-control": ["entity"],
    "weather-forecast": ["entity"],
    "picture-entity": ["entity"],
    "button": ["entity"],
    "light": ["entity"],
    "humidifier": ["entity"],
    "sensor": ["entity"],
    "tile": ["entity"],
    "alarm-panel": ["entity"],
}


def check_dashboard_schema(parsed: Any) -> list[ValidationIssue]:
    """Validate the overall Lovelace dashboard structure."""
    issues: list[ValidationIssue] = []

    if not isinstance(parsed, dict):
        issues.append(
            ValidationIssue(
                check_name="dashboard_schema",
                severity=ValidationSeverity.error,
                message="Dashboard config must be a dict with a 'views' key.",
            )
        )
        return issues

    views = parsed.get("views")
    if views is None:
        issues.append(
            ValidationIssue(
                check_name="dashboard_schema",
                severity=ValidationSeverity.error,
                message="Dashboard config is missing the required 'views' key.",
            )
        )
        return issues

    if not isinstance(views, list):
        issues.append(
            ValidationIssue(
                check_name="dashboard_schema",
                severity=ValidationSeverity.error,
                message="'views' must be a list.",
            )
        )
        return issues

    if len(views) == 0:
        issues.append(
            ValidationIssue(
                check_name="dashboard_schema",
                severity=ValidationSeverity.warning,
                message="Dashboard has no views.",
            )
        )

    for i, view in enumerate(views):
        if not isinstance(view, dict):
            issues.append(
                ValidationIssue(
                    check_name="dashboard_schema",
                    severity=ValidationSeverity.error,
                    message=f"View {i} is not a dict.",
                )
            )
            continue

        cards = view.get("cards")
        if cards is not None and not isinstance(cards, list):
            issues.append(
                ValidationIssue(
                    check_name="dashboard_schema",
                    severity=ValidationSeverity.warning,
                    message=f"View {i} 'cards' should be a list.",
                )
            )

    return issues


def check_card_types(parsed: Any) -> list[ValidationIssue]:
    """Validate card types and required fields within a Lovelace config."""
    issues: list[ValidationIssue] = []

    if not isinstance(parsed, dict):
        return issues

    views = parsed.get("views", [])
    if not isinstance(views, list):
        return issues

    for vi, view in enumerate(views):
        if not isinstance(view, dict):
            continue
        cards = view.get("cards", [])
        if not isinstance(cards, list):
            continue
        issues.extend(_check_cards_recursive(cards, f"view {vi}"))

    return issues


def _check_cards_recursive(
    cards: list, location: str,
) -> list[ValidationIssue]:
    """Recursively check cards, including inside stacks."""
    issues: list[ValidationIssue] = []

    for ci, card in enumerate(cards):
        if not isinstance(card, dict):
            continue

        card_type = card.get("type", "")
        card_loc = f"{location} card {ci}"

        if not card_type:
            issues.append(
                ValidationIssue(
                    check_name="card_type",
                    severity=ValidationSeverity.warning,
                    message=f"{card_loc}: card is missing 'type' field.",
                )
            )
            continue

        if card_type not in VALID_CARD_TYPES:
            issues.append(
                ValidationIssue(
                    check_name="card_type",
                    severity=ValidationSeverity.warning,
                    message=f"{card_loc}: unknown card type '{card_type}'.",
                    suggestion=f"Valid types include: entities, gauge, glance, history-graph, thermostat, media-control",
                )
            )

        # Check required fields
        required = CARD_REQUIRED_FIELDS.get(card_type, [])
        for field in required:
            if field not in card:
                issues.append(
                    ValidationIssue(
                        check_name="card_type",
                        severity=ValidationSeverity.warning,
                        message=f"{card_loc}: '{card_type}' card is missing required field '{field}'.",
                    )
                )

        # Recurse into stack cards
        if card_type in ("horizontal-stack", "vertical-stack", "grid"):
            sub_cards = card.get("cards", [])
            if isinstance(sub_cards, list):
                issues.extend(_check_cards_recursive(sub_cards, card_loc))

    return issues
