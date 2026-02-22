"""Prompt templates for Plan Mode."""

from __future__ import annotations

from autogen.planner.models import ApprovedPlan


PLAN_SYSTEM_PROMPT_AUTOMATION = """\
You are HA AutoGen Planner, an expert Home Assistant automation architect.

## Your Role
You analyse a user's natural language automation request and produce a \
structured PLAN — you do NOT generate YAML. Your plan will be reviewed \
by the user before YAML generation happens in a separate step.

## Output Format
Return a single JSON object inside a ```json code fence with these fields:

```json
{
  "entities_selected": [
    {
      "entity_id": "light.living_room",
      "friendly_name": "Living Room Light",
      "role": "action",
      "alternatives": ["light.living_room_dimmer"]
    }
  ],
  "trigger_outline": "When motion is detected by binary_sensor.living_room_motion...",
  "conditions_outline": "Only after sunset (sun.sun below horizon) and ...",
  "actions_outline": "Turn on light.living_room at 80% brightness, then ...",
  "assumptions": [
    "Assumed you want the light at 80% since no brightness was specified",
    "Using motion sensor in living room, not hallway"
  ],
  "questions": [
    "Should the light turn off automatically after a timeout?",
    "Do you want this to run only on weekdays?"
  ],
  "suggestions": [
    "I also found sensor.living_room_lux — want to add a brightness condition \
so the light only turns on when it's dark?"
  ]
}
```

## Entity Selection Rules
- ONLY select entities from the "Available Entities" list below.
- For each entity, specify its role: "trigger", "condition", "action", or "context".
- "context" means the entity provides useful state info but isn't directly in the automation.
- If multiple entities could serve the same role, pick the best one and list alternatives.

## Plan Quality Rules
1. Be specific — reference exact entity_ids, not vague descriptions.
2. Explain trigger logic in plain English (platform, what state change, etc.).
3. Conditions should include time-of-day, state checks, or any guard the user implied.
4. Actions should describe service calls, data parameters, and sequencing.
5. List every assumption you made — don't hide decisions.
6. Ask questions ONLY when genuinely ambiguous — don't ask obvious things.
7. Suggest related improvements only if you found relevant entities in the context.
"""


PLAN_SYSTEM_PROMPT_DASHBOARD = """\
You are HA AutoGen Planner, an expert Home Assistant Lovelace dashboard architect.

## Your Role
You analyse a user's natural language dashboard request and produce a \
structured PLAN — you do NOT generate YAML. Your plan will be reviewed \
by the user before YAML generation happens in a separate step.

## Output Format
Return a single JSON object inside a ```json code fence with these fields:

```json
{
  "entities_selected": [
    {
      "entity_id": "sensor.temperature",
      "friendly_name": "Temperature",
      "role": "display",
      "alternatives": []
    }
  ],
  "trigger_outline": "",
  "conditions_outline": null,
  "actions_outline": "",
  "layout_outline": "View 1: Living Room — entities card for lights, gauge for \
temperature sensor. View 2: Kitchen — ...",
  "assumptions": [
    "Organizing by room since you said 'all rooms'",
    "Using gauge cards for temperature sensors, entities cards for lights/switches"
  ],
  "questions": [
    "Should I include a separate view for climate controls?"
  ],
  "suggestions": [
    "You have media_player.living_room — want to add a media control card?"
  ]
}
```

## Entity Selection Rules
- ONLY select entities from the "Available Entities" list below.
- For each entity, specify its role: "display" (shown in a card) or "context" (used for conditional display).
- If multiple entities could serve the same purpose, pick the best one and list alternatives.

## Plan Quality Rules
1. Be specific — reference exact entity_ids and card types.
2. The layout_outline should describe each view, its title, and what cards it contains.
3. Match entity domains to appropriate card types (gauge for sensors, thermostat for climate, etc.).
4. Group entities logically by area or function.
5. List every assumption you made.
6. Ask questions ONLY when genuinely ambiguous.
7. Suggest additional entities or views only if they add clear value.
"""


def build_plan_user_prompt(request: str, mode: str) -> str:
    """Build the user prompt for the initial planning call."""
    mode_label = "dashboard" if mode == "dashboard" else "automation"
    return (
        f"## User Request\n\n"
        f"{request}\n\n"
        f"Produce a structured plan for this {mode_label} request. "
        f"Do NOT generate YAML — only return the plan as JSON."
    )


def build_refinement_user_prompt(
    original_request: str,
    previous_plan: ApprovedPlan,
    refinement_notes: str,
    mode: str,
) -> str:
    """Build the user prompt for a plan refinement call."""
    mode_label = "dashboard" if mode == "dashboard" else "automation"

    lines = [
        f"## Original User Request\n\n{original_request}\n",
        "## Previous Plan (user-edited)\n",
        "The user has reviewed your previous plan and made edits. "
        "Here is the current state of the plan as the user left it:\n",
    ]

    if previous_plan.entities_selected:
        lines.append("### Selected Entities (user kept these)")
        for e in previous_plan.entities_selected:
            alt_str = (
                f" (alternatives: {', '.join(e.alternatives)})"
                if e.alternatives
                else ""
            )
            lines.append(
                f"- `{e.entity_id}` — role: {e.role}{alt_str}"
            )
        lines.append("")

    if previous_plan.trigger_outline:
        lines.append(f"### Trigger\n{previous_plan.trigger_outline}\n")
    if previous_plan.conditions_outline:
        lines.append(f"### Conditions\n{previous_plan.conditions_outline}\n")
    if previous_plan.actions_outline:
        lines.append(f"### Actions\n{previous_plan.actions_outline}\n")
    if previous_plan.layout_outline:
        lines.append(f"### Layout\n{previous_plan.layout_outline}\n")

    if previous_plan.assumptions:
        lines.append("### Accepted Assumptions")
        for a in previous_plan.assumptions:
            lines.append(f"- {a}")
        lines.append("")

    if previous_plan.answered_questions:
        lines.append("### User Answers to Questions")
        for q, a in previous_plan.answered_questions.items():
            lines.append(f"- Q: {q}")
            lines.append(f"  A: {a}")
        lines.append("")

    lines.append(f"## Refinement Instructions\n\n{refinement_notes}\n")
    lines.append(
        f"Update the plan for this {mode_label} based on the user's edits "
        f"and refinement instructions above. Return the updated plan as JSON."
    )

    return "\n".join(lines)


def build_generate_from_plan_user_prompt(
    original_request: str,
    plan: ApprovedPlan,
    mode: str,
) -> str:
    """Build the user prompt for the final generation call (from approved plan)."""
    mode_label = "Lovelace dashboard" if mode == "dashboard" else "automation"

    lines = [
        f"## User Request\n\n{original_request}\n",
        "## Approved Plan\n",
        "The user has reviewed and approved the following plan. "
        "Generate YAML that implements it exactly.\n",
    ]

    if plan.entities_selected:
        lines.append("### Selected Entities")
        for e in plan.entities_selected:
            alt_str = (
                f" (alternatives: {', '.join(e.alternatives)})"
                if e.alternatives
                else ""
            )
            lines.append(
                f"- `{e.entity_id}` — role: {e.role}{alt_str}"
            )
        lines.append("")

    if plan.trigger_outline:
        lines.append(f"### Trigger\n{plan.trigger_outline}\n")
    if plan.conditions_outline:
        lines.append(f"### Conditions\n{plan.conditions_outline}\n")
    if plan.actions_outline:
        lines.append(f"### Actions\n{plan.actions_outline}\n")
    if plan.layout_outline:
        lines.append(f"### Layout\n{plan.layout_outline}\n")

    if plan.assumptions:
        lines.append("### Accepted Assumptions")
        for a in plan.assumptions:
            lines.append(f"- {a}")
        lines.append("")

    if plan.answered_questions:
        lines.append("### User Answers")
        for q, a in plan.answered_questions.items():
            lines.append(f"- Q: {q}")
            lines.append(f"  A: {a}")
        lines.append("")

    if plan.user_notes:
        lines.append(f"### Additional Notes\n{plan.user_notes}\n")

    lines.append(
        f"Generate a Home Assistant {mode_label} YAML for this approved plan."
    )

    return "\n".join(lines)
