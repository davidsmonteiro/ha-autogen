"""Automation generation prompt assembly."""

from __future__ import annotations

from autogen.context.entities import EntityEntry
from autogen.context.areas import AreaEntry


def build_context_block(
    entities: list[EntityEntry],
    areas: list[AreaEntry],
) -> str:
    """Format entity and area data as a text block for the LLM prompt."""
    lines: list[str] = ["## Available Entities"]

    area_map = {a.area_id: a.name for a in areas}
    by_area: dict[str | None, list[EntityEntry]] = {}
    for e in entities:
        by_area.setdefault(e.area_id, []).append(e)

    for area_id, area_entities in sorted(
        by_area.items(), key=lambda x: (x[0] is None, x[0] or "")
    ):
        area_name = area_map.get(area_id, "Unassigned") if area_id else "Unassigned"
        lines.append(f"\n### {area_name}")
        for ent in sorted(area_entities, key=lambda e: e.entity_id):
            display = ent.name or ent.entity_id
            lines.append(f"- `{ent.entity_id}` ({display})")

    return "\n".join(lines)


def build_user_prompt(request: str) -> str:
    """Wrap the user's natural language request into the user prompt."""
    return (
        f"## User Request\n\n"
        f"{request}\n\n"
        f"Generate a Home Assistant automation YAML for this request."
    )
