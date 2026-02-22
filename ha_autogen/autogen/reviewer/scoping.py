"""Review scoping utilities — filter configs by area for targeted review."""

from __future__ import annotations

import re
from typing import Any

# Pattern matching HA entity IDs: domain.object_id
ENTITY_ID_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z0-9_]+$")


def extract_entity_ids_from_automation(automation: dict[str, Any]) -> set[str]:
    """Recursively walk an automation dict and extract all entity_id values.

    Handles common HA automation keys: ``entity_id``, ``entity``,
    ``entities``, plus list and nested dict structures found in
    triggers, conditions, and actions.
    """
    results: set[str] = set()
    _walk(automation, results)
    return results


def _walk(obj: Any, results: set[str]) -> None:
    """Recursively walk a structure, collecting entity IDs."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in ("entity_id", "entity"):
                if isinstance(value, str) and ENTITY_ID_RE.match(value):
                    results.add(value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str) and ENTITY_ID_RE.match(item):
                            results.add(item)
            elif key == "entities":
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, str) and ENTITY_ID_RE.match(item):
                            results.add(item)
                        elif isinstance(item, dict) and "entity" in item:
                            eid = item["entity"]
                            if isinstance(eid, str) and ENTITY_ID_RE.match(eid):
                                results.add(eid)
            _walk(value, results)
    elif isinstance(obj, list):
        for item in obj:
            _walk(item, results)


def filter_automations_by_area(
    automations: list[dict[str, Any]],
    area_id: str,
    entity_area_map: dict[str, str | None],
) -> list[dict[str, Any]]:
    """Return automations that reference at least one entity in *area_id*."""
    result: list[dict[str, Any]] = []
    for auto in automations:
        entity_ids = extract_entity_ids_from_automation(auto)
        for eid in entity_ids:
            if entity_area_map.get(eid) == area_id:
                result.append(auto)
                break
    return result


def filter_dashboard_views_by_area(
    dashboard: dict[str, Any],
    area_id: str,
    entity_area_map: dict[str, str | None],
    area_names: dict[str, str],
) -> dict[str, Any]:
    """Return a dashboard dict with only views relevant to *area_id*.

    A view is relevant if:
    - Its title matches the area name (case-insensitive), OR
    - It contains cards that reference entities in the given area.
    """
    area_name = area_names.get(area_id, "").lower()
    views = dashboard.get("views", [])
    filtered_views: list[dict[str, Any]] = []

    for view in views:
        # Title match
        view_title = (view.get("title") or "").lower()
        if area_name and area_name in view_title:
            filtered_views.append(view)
            continue

        # Entity match
        entity_ids: set[str] = set()
        _walk(view, entity_ids)
        for eid in entity_ids:
            if entity_area_map.get(eid) == area_id:
                filtered_views.append(view)
                break

    return {"views": filtered_views}


def filter_dashboard_view_by_path(
    dashboard: dict[str, Any],
    view_path: str,
) -> dict[str, Any]:
    """Extract a single view by its ``path`` field.

    Falls back to index-based matching (``view-0``, ``view-1``, etc.).
    """
    views = dashboard.get("views", [])

    for view in views:
        if view.get("path") == view_path:
            return {"views": [view]}

    # Fallback: try index
    if view_path.startswith("view-"):
        try:
            idx = int(view_path.removeprefix("view-"))
            if 0 <= idx < len(views):
                return {"views": [views[idx]]}
        except ValueError:
            pass

    return {"views": []}
