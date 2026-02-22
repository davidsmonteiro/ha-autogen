"""Deterministic dashboard review rules."""

from __future__ import annotations

from autogen.reviewer.models import (
    FindingCategory,
    FindingSeverity,
    ReviewFinding,
)

# Card type recommendations per entity domain
RECOMMENDED_CARD_TYPES: dict[str, str] = {
    "sensor": "gauge",
    "climate": "thermostat",
    "media_player": "media-control",
    "weather": "weather-forecast",
    "camera": "picture-entity",
}


def _collect_card_entities(cards: list[dict]) -> list[tuple[str, str]]:
    """Recursively collect (entity_id, card_type) pairs from cards."""
    pairs: list[tuple[str, str]] = []
    for card in cards:
        card_type = card.get("type", "")
        # Stack cards contain nested cards
        if card_type in ("horizontal-stack", "vertical-stack"):
            nested = card.get("cards", [])
            pairs.extend(_collect_card_entities(nested))
            continue
        # Single-entity cards
        entity = card.get("entity")
        if entity:
            pairs.append((entity, card_type))
        # Multi-entity cards (entities card, glance card)
        entities = card.get("entities", [])
        for ent in entities:
            if isinstance(ent, str):
                pairs.append((ent, card_type))
            elif isinstance(ent, dict) and "entity" in ent:
                pairs.append((ent["entity"], card_type))
    return pairs


def _collect_dashboard_entities(dashboard: dict) -> list[tuple[str, str]]:
    """Collect all (entity_id, card_type) pairs from a dashboard config."""
    pairs: list[tuple[str, str]] = []
    for view in dashboard.get("views", []):
        cards = view.get("cards", [])
        pairs.extend(_collect_card_entities(cards))
    return pairs


def check_unused_entities(
    dashboard: dict, known_entity_ids: set[str],
) -> list[ReviewFinding]:
    """Find entities in HA that are not on any dashboard card."""
    dashboard_entities = {eid for eid, _ in _collect_dashboard_entities(dashboard)}

    # Only check active entity domains that typically belong on dashboards
    displayable_domains = {
        "light", "switch", "sensor", "binary_sensor", "climate",
        "cover", "media_player", "fan", "lock", "camera", "weather",
        "vacuum", "humidifier", "water_heater",
    }

    unused = []
    for eid in sorted(known_entity_ids):
        domain = eid.split(".")[0] if "." in eid else ""
        if domain in displayable_domains and eid not in dashboard_entities:
            unused.append(eid)

    if not unused:
        return []

    # Group by domain for a concise summary
    by_domain: dict[str, list[str]] = {}
    for eid in unused:
        domain = eid.split(".")[0]
        by_domain.setdefault(domain, []).append(eid)

    # Build a compact summary: domain counts + a few examples per domain
    MAX_EXAMPLES = 3
    desc_parts = [
        f"{len(unused)} entities across {len(by_domain)} domain(s) are not "
        f"on any dashboard card:\n"
    ]
    for domain, eids in sorted(by_domain.items()):
        examples = ", ".join(eids[:MAX_EXAMPLES])
        if len(eids) > MAX_EXAMPLES:
            examples += f" (+{len(eids) - MAX_EXAMPLES} more)"
        desc_parts.append(f"  {domain}: {len(eids)} — {examples}")

    desc_parts.append(
        "\nConsider adding views or cards for the most important "
        "entities, or filtering out entities you don't need on the dashboard."
    )

    return [
        ReviewFinding(
            severity=FindingSeverity.suggestion,
            category=FindingCategory.unused_entities,
            title=f"{len(unused)} entities not on any dashboard card",
            description="\n".join(desc_parts),
        )
    ]


def check_inconsistent_cards(dashboard: dict) -> list[ReviewFinding]:
    """Find entities of the same domain using different card types."""
    pairs = _collect_dashboard_entities(dashboard)

    # Group card types by entity domain
    domain_card_types: dict[str, set[str]] = {}
    for eid, card_type in pairs:
        domain = eid.split(".")[0] if "." in eid else ""
        if domain:
            domain_card_types.setdefault(domain, set()).add(card_type)

    findings: list[ReviewFinding] = []
    for domain, card_types in sorted(domain_card_types.items()):
        if len(card_types) > 1:
            findings.append(
                ReviewFinding(
                    severity=FindingSeverity.suggestion,
                    category=FindingCategory.inconsistent_cards,
                    title=f"Inconsistent card types for '{domain}' domain",
                    description=(
                        f"Entities in the '{domain}' domain use multiple card "
                        f"types: {', '.join(sorted(card_types))}. Consider "
                        f"using a consistent card type for visual cohesion."
                    ),
                )
            )

    return findings


def check_missing_area_coverage(
    dashboard: dict, areas: list,
) -> list[ReviewFinding]:
    """Find areas that have entities but no dedicated dashboard view."""
    view_titles = set()
    for view in dashboard.get("views", []):
        title = view.get("title", "").lower()
        if title:
            view_titles.add(title)

    findings: list[ReviewFinding] = []
    for area in areas:
        # Support both dicts and Pydantic AreaEntry objects
        area_name = area.get("name", "") if isinstance(area, dict) else getattr(area, "name", "")
        if not area_name:
            continue
        # Check if any view title matches the area name (case-insensitive)
        if area_name.lower() not in view_titles:
            findings.append(
                ReviewFinding(
                    severity=FindingSeverity.suggestion,
                    category=FindingCategory.missing_area_coverage,
                    title=f"No dashboard view for area: {area_name}",
                    description=(
                        f"The area '{area_name}' exists in Home Assistant but "
                        f"has no matching dashboard view. Consider adding a view "
                        f"for this area to provide full coverage."
                    ),
                )
            )

    return findings


def check_card_type_recommendations(dashboard: dict) -> list[ReviewFinding]:
    """Suggest better card types based on entity domains."""
    pairs = _collect_dashboard_entities(dashboard)

    # Track which entities could use a better card type
    suggestions: dict[str, list[str]] = {}
    for eid, card_type in pairs:
        domain = eid.split(".")[0] if "." in eid else ""
        recommended = RECOMMENDED_CARD_TYPES.get(domain)
        if recommended and card_type != recommended and card_type != "":
            key = f"{domain}:{card_type}→{recommended}"
            suggestions.setdefault(key, []).append(eid)

    findings: list[ReviewFinding] = []
    for key, entities in suggestions.items():
        domain, change = key.split(":", 1)
        current, suggested = change.split("→")
        findings.append(
            ReviewFinding(
                severity=FindingSeverity.info,
                category=FindingCategory.card_type_recommendation,
                title=f"Consider '{suggested}' card for {domain} entities",
                description=(
                    f"{len(entities)} {domain} entity/entities use '{current}' "
                    f"cards. The '{suggested}' card type is designed for "
                    f"{domain} entities and may provide a better experience. "
                    f"Entities: {', '.join(entities[:5])}"
                    + (f" (+{len(entities) - 5} more)" if len(entities) > 5 else "")
                ),
            )
        )

    return findings


def check_layout_optimization(dashboard: dict) -> list[ReviewFinding]:
    """Flag layout issues like overly long views or missing stacks."""
    findings: list[ReviewFinding] = []

    for view in dashboard.get("views", []):
        title = view.get("title", "Unnamed")
        cards = view.get("cards", [])

        # Check for long single-column views (more than 8 top-level cards)
        if len(cards) > 8:
            has_stacks = any(
                c.get("type") in ("horizontal-stack", "vertical-stack")
                for c in cards
            )
            if not has_stacks:
                findings.append(
                    ReviewFinding(
                        severity=FindingSeverity.suggestion,
                        category=FindingCategory.layout_optimization,
                        title=f"Long single-column layout in '{title}'",
                        description=(
                            f"The '{title}' view has {len(cards)} top-level "
                            f"cards with no stack grouping. Consider using "
                            f"horizontal-stack or vertical-stack cards to "
                            f"organize related cards and reduce scrolling."
                        ),
                    )
                )

    return findings


def run_all_dashboard_rules(
    dashboard: dict,
    known_entity_ids: set[str] | None = None,
    areas: list[dict] | None = None,
) -> list[ReviewFinding]:
    """Run all deterministic dashboard review rules."""
    findings: list[ReviewFinding] = []

    if known_entity_ids is not None:
        findings.extend(check_unused_entities(dashboard, known_entity_ids))

    findings.extend(check_inconsistent_cards(dashboard))

    if areas is not None:
        findings.extend(check_missing_area_coverage(dashboard, areas))

    findings.extend(check_card_type_recommendations(dashboard))
    findings.extend(check_layout_optimization(dashboard))

    return findings
