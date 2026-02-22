"""Explore prompt — automation suggestion generation via LLM."""

from __future__ import annotations

from autogen.explorer.analysis import AreaProfile, InventoryAnalysis

EXPLORE_SYSTEM_PROMPT = """\
You are HA AutoGen Explorer, an expert at identifying useful Home Assistant \
automations based on available devices and entities.

## Your Role
Given an inventory analysis of a Home Assistant instance, suggest automations \
that would add the most value. Focus on practical, everyday automations.

## Output Format
Return a JSON array of automation suggestions inside a ```json code fence:

```json
[
  {
    "title": "Short descriptive title",
    "description": "1-2 sentence explanation of what this automation does and why it's useful",
    "entities_involved": ["entity_id_1", "entity_id_2"],
    "area": "Area Name",
    "complexity": "simple",
    "category": "lighting",
    "example_yaml": "alias: Title\\ntrigger:\\n  - platform: state\\n    entity_id: binary_sensor.motion\\n    to: 'on'\\naction:\\n  - service: light.turn_on\\n    target:\\n      entity_id: light.living_room"
  }
]
```

## Rules
1. ONLY use entity_ids from the provided inventory — NEVER invent entity IDs.
2. Do NOT suggest automations that already exist (check the existing automations list).
3. Suggest 5-10 automations, ordered by estimated value/usefulness.
4. Prefer simple, high-impact automations over complex niche ones.
5. Cover different areas and categories when possible.
6. The example_yaml must be valid HA automation YAML (no code fences inside).
7. Valid complexity values: simple, moderate, advanced.
8. Valid category values: lighting, security, comfort, energy, convenience, notification.
"""


def build_explore_user_prompt(
    analysis: InventoryAnalysis,
    focus_area: str | None = None,
    focus_domain: str | None = None,
) -> str:
    """Build the user prompt for the explore LLM call."""
    parts: list[str] = ["## Home Assistant Inventory Analysis"]

    parts.append(
        f"\nTotal: {analysis.total_entities} entities, "
        f"{analysis.total_areas} areas, "
        f"{analysis.total_automations} existing automations. "
        f"Coverage: {analysis.coverage_percent:.1f}%."
    )

    if focus_area:
        parts.append(f"\n**Focus on area: {focus_area}**")
    if focus_domain:
        parts.append(f"\n**Focus on domain: {focus_domain}**")

    # Area profiles
    profiles_to_show = analysis.area_profiles
    if focus_area:
        profiles_to_show = [
            p for p in profiles_to_show
            if p.area_name.lower() == focus_area.lower()
            or p.area_id == focus_area
        ]

    if profiles_to_show:
        parts.append("\n## Areas with Automation Potential")
        for profile in profiles_to_show[:10]:
            parts.append(_format_area_profile(profile, focus_domain))

    # Unautomated entities summary
    if analysis.unautomated_entity_ids:
        unautomated = sorted(analysis.unautomated_entity_ids)
        if focus_domain:
            unautomated = [e for e in unautomated if e.startswith(f"{focus_domain}.")]

        if unautomated:
            parts.append(f"\n## Unautomated Entities ({len(unautomated)} total)")
            for eid in unautomated[:50]:
                parts.append(f"- `{eid}`")
            if len(unautomated) > 50:
                parts.append(f"... and {len(unautomated) - 50} more")

    # Existing automations (for deduplication)
    if analysis.total_automations > 0:
        parts.append(
            f"\n## Existing Automations ({analysis.total_automations} total)"
        )
        parts.append("(Do NOT suggest automations that duplicate these)")
        # Automated entities summary
        automated = sorted(analysis.automated_entity_ids)[:30]
        for eid in automated:
            parts.append(f"- `{eid}` (already automated)")
        if len(analysis.automated_entity_ids) > 30:
            parts.append(f"... and {len(analysis.automated_entity_ids) - 30} more")

    parts.append(
        "\n\nSuggest 5-10 valuable automations based on this inventory."
    )

    return "\n".join(parts)


def _format_area_profile(profile: AreaProfile, focus_domain: str | None = None) -> str:
    """Format a single area profile for the prompt."""
    lines: list[str] = [
        f"\n### {profile.area_name} ({profile.coverage_percent:.0f}% coverage, "
        f"{len(profile.potential_patterns)} patterns)"
    ]

    domains = profile.entities_by_domain
    if focus_domain:
        domains = {k: v for k, v in domains.items() if k == focus_domain}

    for domain, entity_ids in sorted(domains.items()):
        sample = ", ".join(f"`{e}`" for e in entity_ids[:5])
        extra = f" (+{len(entity_ids) - 5} more)" if len(entity_ids) > 5 else ""
        lines.append(f"- **{domain}** ({len(entity_ids)}): {sample}{extra}")

    return "\n".join(lines)
