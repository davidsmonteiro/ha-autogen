"""Deterministic inventory analysis for the automation explorer.

Identifies entity combinations that could be automated (motion+light,
contact+lock, etc.) and computes coverage metrics per area.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from autogen.context.areas import AreaEntry
from autogen.context.entities import EntityEntry
from autogen.reviewer.scoping import extract_entity_ids_from_automation


# ---------------------------------------------------------------------------
# Known automation patterns — (trigger_domain, target_domain, category, title)
# ---------------------------------------------------------------------------

AUTOMATION_PATTERNS: list[tuple[str, str, str, str]] = [
    ("binary_sensor", "light", "lighting", "Turn lights on/off with motion"),
    ("binary_sensor", "switch", "convenience", "Toggle switch with sensor"),
    ("binary_sensor", "lock", "security", "Lock/unlock door with sensor"),
    ("binary_sensor", "cover", "comfort", "Open/close cover with sensor"),
    ("binary_sensor", "alarm_control_panel", "security", "Arm alarm when door closes"),
    ("sensor", "climate", "comfort", "Adjust climate based on temperature"),
    ("sensor", "light", "comfort", "Adjust lighting based on illuminance"),
    ("sensor", "notification", "notification", "Alert on sensor threshold"),
    ("device_tracker", "light", "lighting", "Turn lights on when arriving home"),
    ("device_tracker", "switch", "convenience", "Toggle devices based on presence"),
    ("device_tracker", "lock", "security", "Lock doors when everyone leaves"),
    ("sun", "light", "lighting", "Turn lights on at sunset"),
    ("sun", "cover", "comfort", "Close covers at sunset"),
    ("media_player", "light", "lighting", "Dim lights during media playback"),
    ("weather", "cover", "comfort", "Adjust covers based on weather"),
    ("camera", "binary_sensor", "security", "Record on motion detection"),
]


@dataclass
class MatchedPattern:
    """A pattern match found in a specific area."""

    trigger_domain: str
    target_domain: str
    category: str
    title: str
    area_id: str
    area_name: str
    trigger_entities: list[str] = field(default_factory=list)
    target_entities: list[str] = field(default_factory=list)


@dataclass
class AreaProfile:
    """Analysis of a single area's automation potential."""

    area_id: str
    area_name: str
    entities_by_domain: dict[str, list[str]] = field(default_factory=dict)
    automated_entity_ids: set[str] = field(default_factory=set)
    total_entities: int = 0
    automated_count: int = 0
    coverage_percent: float = 0.0
    potential_patterns: list[MatchedPattern] = field(default_factory=list)


@dataclass
class InventoryAnalysis:
    """Complete inventory analysis result."""

    total_entities: int = 0
    total_areas: int = 0
    total_automations: int = 0
    automated_entity_ids: set[str] = field(default_factory=set)
    unautomated_entity_ids: set[str] = field(default_factory=set)
    area_profiles: list[AreaProfile] = field(default_factory=list)
    matched_patterns: list[MatchedPattern] = field(default_factory=list)
    coverage_percent: float = 0.0


def extract_automated_entities(automations: list[dict[str, Any]]) -> set[str]:
    """Extract all entity IDs referenced in existing automations."""
    all_ids: set[str] = set()
    for auto in automations:
        all_ids.update(extract_entity_ids_from_automation(auto))
    return all_ids


def analyze_inventory(
    entities: list[EntityEntry],
    areas: list[AreaEntry],
    automations: list[dict[str, Any]],
) -> InventoryAnalysis:
    """Run deterministic analysis of the HA inventory.

    Identifies unautomated entities, matches automation patterns by area,
    and computes coverage metrics.
    """
    area_map = {a.area_id: a.name for a in areas}
    automated_ids = extract_automated_entities(automations)

    # Group active entities by area
    entities_by_area: dict[str | None, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    all_entity_ids: set[str] = set()

    for e in entities:
        if e.disabled_by is not None or e.hidden_by is not None:
            continue
        all_entity_ids.add(e.entity_id)
        entities_by_area[e.area_id][e.domain].append(e.entity_id)

    unautomated_ids = all_entity_ids - automated_ids

    # Build area profiles and match patterns
    area_profiles: list[AreaProfile] = []
    all_patterns: list[MatchedPattern] = []

    for area in areas:
        domains = entities_by_area.get(area.area_id, {})
        if not domains:
            continue

        area_entities: set[str] = set()
        for domain_entities in domains.values():
            area_entities.update(domain_entities)

        area_automated = area_entities & automated_ids
        total = len(area_entities)
        coverage = (len(area_automated) / total * 100) if total else 0.0

        # Match patterns
        patterns: list[MatchedPattern] = []
        for trigger_domain, target_domain, category, title in AUTOMATION_PATTERNS:
            triggers = domains.get(trigger_domain, [])
            targets = domains.get(target_domain, [])
            if triggers and targets:
                # Only suggest if at least one entity is unautomated
                unautomated_in_pattern = (
                    (set(triggers) | set(targets)) & unautomated_ids
                )
                if unautomated_in_pattern:
                    pattern = MatchedPattern(
                        trigger_domain=trigger_domain,
                        target_domain=target_domain,
                        category=category,
                        title=title,
                        area_id=area.area_id,
                        area_name=area.name,
                        trigger_entities=triggers[:3],
                        target_entities=targets[:3],
                    )
                    patterns.append(pattern)
                    all_patterns.append(pattern)

        profile = AreaProfile(
            area_id=area.area_id,
            area_name=area.name,
            entities_by_domain=dict(domains),
            automated_entity_ids=area_automated,
            total_entities=total,
            automated_count=len(area_automated),
            coverage_percent=coverage,
            potential_patterns=patterns,
        )
        area_profiles.append(profile)

    # Sort by most potential (most unmatched patterns first)
    area_profiles.sort(key=lambda p: -len(p.potential_patterns))

    overall_coverage = (
        len(automated_ids & all_entity_ids) / len(all_entity_ids) * 100
        if all_entity_ids
        else 0.0
    )

    return InventoryAnalysis(
        total_entities=len(all_entity_ids),
        total_areas=len(areas),
        total_automations=len(automations),
        automated_entity_ids=automated_ids & all_entity_ids,
        unautomated_entity_ids=unautomated_ids,
        area_profiles=area_profiles,
        matched_patterns=all_patterns,
        coverage_percent=overall_coverage,
    )
