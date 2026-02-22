"""Entity reference validation — cross-check entity IDs against the live registry."""

from __future__ import annotations

import difflib
import re
from typing import Any

from autogen.validator.models import ValidationIssue, ValidationSeverity

# Pattern matching HA entity IDs: domain.object_id
ENTITY_ID_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z0-9_]+$")


def _extract_entity_ids(obj: Any, path: str = "") -> list[tuple[str, str]]:
    """Recursively walk a parsed YAML dict and extract likely entity_id values.

    Handles automation keys (entity_id) and Lovelace keys (entity, entities).
    Returns list of (entity_id, path_description) tuples.
    """
    results: list[tuple[str, str]] = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            current_path = f"{path}.{key}" if path else key
            if key in ("entity_id", "entity"):
                if isinstance(value, str) and ENTITY_ID_RE.match(value):
                    results.append((value, current_path))
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str) and ENTITY_ID_RE.match(item):
                            results.append((item, current_path))
            elif key == "entities":
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, str) and ENTITY_ID_RE.match(item):
                            results.append((item, current_path))
                        elif isinstance(item, dict) and "entity" in item:
                            eid = item["entity"]
                            if isinstance(eid, str) and ENTITY_ID_RE.match(eid):
                                results.append((eid, current_path))
                results.extend(_extract_entity_ids(value, current_path))
            else:
                results.extend(_extract_entity_ids(value, current_path))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            results.extend(_extract_entity_ids(item, f"{path}[{i}]"))

    return results


def check_entity_refs(
    parsed_yaml: dict,
    known_entity_ids: set[str],
) -> list[ValidationIssue]:
    """Check all entity_id references against the known entity registry.

    Returns a list of warning-level issues for unknown entity IDs,
    with fuzzy-match suggestions where possible.
    """
    issues: list[ValidationIssue] = []
    found_refs = _extract_entity_ids(parsed_yaml)

    for entity_id, path in found_refs:
        if entity_id not in known_entity_ids:
            # Try fuzzy matching
            suggestion = None
            matches = difflib.get_close_matches(
                entity_id, list(known_entity_ids), n=1, cutoff=0.6
            )
            if matches:
                suggestion = f"Did you mean: {matches[0]}?"

            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.warning,
                    check_name="entity_refs",
                    message=f"Unknown entity_id '{entity_id}' at {path}",
                    suggestion=suggestion,
                )
            )

    return issues
