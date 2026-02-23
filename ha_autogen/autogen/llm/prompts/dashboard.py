"""Dashboard generation prompt assembly."""

from __future__ import annotations

from autogen.context.areas import AreaEntry
from autogen.context.entities import EntityEntry

DASHBOARD_SYSTEM_PROMPT = """\
You are HA AutoGen, an expert Home Assistant Lovelace dashboard generator.

## Your Role
You generate valid Home Assistant Lovelace dashboard YAML configurations based on \
natural language requests. You ONLY use entity IDs from the provided context.

## Output Rules
1. Return ONLY the Lovelace YAML inside a single ```yaml code fence.
2. Do NOT include any text before or after the code fence.
3. The YAML must be a valid Lovelace dashboard configuration with a `views` list.
4. Include inline comments explaining non-obvious groupings.
5. Use area-based view organization when the user mentions rooms or areas.

## Lovelace Dashboard Structure
```yaml
views:
  - title: "Room Name"
    path: room-name
    cards:
      - type: entities
        title: "Lights"
        entities:
          - entity: light.living_room
          - entity: light.kitchen
      - type: gauge
        entity: sensor.temperature
        name: "Temperature"
        min: 0
        max: 50
```

## Supported Card Types
- **entities**: List of entities with optional names/icons. \
Best for mixed entity groups.
- **gauge**: Circular gauge for numeric sensors (temperature, humidity, power). \
Requires: entity, min, max.
- **history-graph**: Time-series graph for trending sensors. \
Requires: entities list. Best for temperature, humidity, power over time.
- **thermostat**: Climate control card. Requires: entity (climate.*).
- **media-control**: Media player controls. Requires: entity (media_player.*).
- **weather-forecast**: Weather display. Requires: entity (weather.*).
- **glance**: Compact multi-entity overview. Best for quick status of many entities.
- **picture-entity**: Entity with camera/picture. Requires: entity (camera.*).
- **horizontal-stack** / **vertical-stack**: Layout containers for grouping cards.

## Card Type Selection Guide
- `sensor.*` with unit_of_measurement → `gauge` or `history-graph`
- `climate.*` → `thermostat`
- `media_player.*` → `media-control`
- `weather.*` → `weather-forecast`
- `camera.*` → `picture-entity`
- `binary_sensor.*`, `switch.*`, `light.*` → `entities` or `glance`
- Multiple related sensors → `history-graph` for trends

## Critical Rules
- ONLY use entity_ids from the "Available Entities" list below.
- NEVER invent entity_ids that are not in the provided context.
- Create one view per area/room when the user asks for "all rooms" or a multi-room dashboard.
- Group related entities logically within each view.
- Use the most appropriate card type for each entity domain.
- Keep view titles human-readable (use area names, not IDs).
"""


def build_dashboard_context_block(
    entities: list[EntityEntry],
    areas: list[AreaEntry],
    budget_tokens: int = 0,
) -> str:
    """Format entity and area data grouped by area for dashboard prompts.

    Groups entities under area headings so the LLM can see which entities
    belong to each room. Respects a token budget — when exhausted, remaining
    areas are summarised as domain counts.
    """
    from autogen.context.token_budget import estimate_tokens

    area_map = {a.area_id: a.name for a in areas}
    by_area: dict[str | None, list[EntityEntry]] = {}
    for e in entities:
        by_area.setdefault(e.area_id, []).append(e)

    lines: list[str] = ["## Available Entities"]
    tokens_used = estimate_tokens(lines[0])

    # Sort areas: named areas first alphabetically, then Unassigned last
    sorted_areas = sorted(
        by_area.items(), key=lambda x: (x[0] is None, area_map.get(x[0], "ZZZ") if x[0] else "ZZZ"),
    )

    overflow_entities: list[EntityEntry] = []

    for area_id, area_entities in sorted_areas:
        area_name = area_map.get(area_id, "Unassigned") if area_id else "Unassigned"
        header = f"\n### {area_name}"
        header_cost = estimate_tokens(header)

        # Check if we can fit at least the header + 1 entity
        per_entity_cost = 20  # approx tokens for "- `entity_id` (Friendly Name)"
        if budget_tokens and tokens_used + header_cost + per_entity_cost > budget_tokens:
            overflow_entities.extend(area_entities)
            continue

        lines.append(header)
        tokens_used += header_cost

        for ent in sorted(area_entities, key=lambda e: e.entity_id):
            if budget_tokens and tokens_used + per_entity_cost > budget_tokens:
                overflow_entities.append(ent)
                continue
            display = ent.name or ent.entity_id
            lines.append(f"- `{ent.entity_id}` ({display})")
            tokens_used += per_entity_cost

    # Summarise overflow as domain counts
    if overflow_entities:
        from collections import defaultdict
        domain_counts: dict[str, int] = defaultdict(int)
        for ent in overflow_entities:
            domain_counts[ent.domain] += 1
        parts = [f"{count} {domain}" for domain, count in sorted(domain_counts.items(), key=lambda x: -x[1])]
        lines.append(f"\n+ {', '.join(parts)} entities in other areas")

    return "\n".join(lines)


def build_dashboard_user_prompt(request: str) -> str:
    """Wrap the user's request into the dashboard generation user prompt."""
    return (
        f"## User Request\n\n"
        f"{request}\n\n"
        f"Generate a Home Assistant Lovelace dashboard YAML for this request. "
        f"The output must be a valid Lovelace config with a `views` list."
    )
