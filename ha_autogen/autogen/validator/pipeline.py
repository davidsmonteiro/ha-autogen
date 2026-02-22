"""Validation pipeline — orchestrates all checks in sequence."""

from __future__ import annotations

from autogen.validator.dashboard_schema import check_card_types, check_dashboard_schema
from autogen.validator.entity_refs import check_entity_refs
from autogen.validator.models import ValidationResult
from autogen.validator.service_calls import check_service_calls
from autogen.validator.yaml_syntax import check_yaml_syntax


def validate(yaml_str: str, known_entity_ids: set[str]) -> ValidationResult:
    """Run the full validation pipeline on generated YAML.

    Order: 1. YAML syntax → 2. Entity refs → 3. Service calls.
    If syntax fails, returns immediately (can't check refs/services without parsed YAML).
    """
    # Step 1: YAML syntax
    result = check_yaml_syntax(yaml_str)
    if not result.valid or result.yaml_parsed is None:
        return result

    # Step 2: Entity reference cross-check
    entity_issues = check_entity_refs(result.yaml_parsed, known_entity_ids)
    result.issues.extend(entity_issues)

    # Step 3: Service call validation
    service_issues = check_service_calls(result.yaml_parsed)
    result.issues.extend(service_issues)

    return result


def validate_dashboard(yaml_str: str, known_entity_ids: set[str]) -> ValidationResult:
    """Run dashboard-specific validation pipeline on generated YAML.

    Order: 1. YAML syntax → 2. Dashboard schema → 3. Card types → 4. Entity refs.
    """
    result = check_yaml_syntax(yaml_str)
    if not result.valid or result.yaml_parsed is None:
        return result

    schema_issues = check_dashboard_schema(result.yaml_parsed)
    result.issues.extend(schema_issues)
    if any(i.severity.value == "error" for i in schema_issues):
        result.valid = False
        return result

    card_issues = check_card_types(result.yaml_parsed)
    result.issues.extend(card_issues)

    entity_issues = check_entity_refs(result.yaml_parsed, known_entity_ids)
    result.issues.extend(entity_issues)

    return result
