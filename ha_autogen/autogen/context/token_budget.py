"""Token-aware context management for LLM prompt construction.

Uses a character-based heuristic to estimate tokens without external
dependencies.  Builds a three-tier entity context that fits within
a model's context window: full detail → compact → domain summary.
"""

from __future__ import annotations

import os
from collections import defaultdict

from autogen.context.areas import AreaEntry
from autogen.context.entities import EntityEntry

# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Estimate token count from text using a conservative character heuristic.

    ~3 characters per token is conservative for English text with code-like
    identifiers (entity IDs, YAML keys).  Errs on the high side so we don't
    exceed the real limit.
    """
    return len(text) // 3


# ---------------------------------------------------------------------------
# Model context windows
# ---------------------------------------------------------------------------

MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # Local / Ollama models
    "llama3.2": 8192,
    "llama3.2:1b": 8192,
    "llama3.2:3b": 8192,
    "llama3.1": 131072,
    "llama3.1:8b": 131072,
    "llama3.1:70b": 131072,
    "mistral": 32768,
    "mistral:7b": 32768,
    "mixtral": 32768,
    "codellama": 16384,
    "phi3": 4096,
    "phi3:mini": 4096,
    "gemma2": 8192,
    "qwen2.5": 32768,
    # Cloud models
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
    "gpt-3.5-turbo": 16385,
    "claude-3-opus": 200000,
    "claude-3-sonnet": 200000,
    "claude-3-haiku": 200000,
    "claude-3.5-sonnet": 200000,
    "claude-sonnet-4-6": 200000,
    "claude-opus-4-6": 200000,
}


def get_context_window(model_name: str, default: int = 8192) -> int:
    """Look up context window size for a model.

    Checks ``AUTOGEN_MODEL_CONTEXT_WINDOW`` env var first (allows user
    override), then falls back to the built-in table, then *default*.
    """
    env_override = os.environ.get("AUTOGEN_MODEL_CONTEXT_WINDOW")
    if env_override:
        try:
            return int(env_override)
        except ValueError:
            pass

    # Try exact match, then prefix match (e.g. "llama3.2:latest" → "llama3.2")
    if model_name in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model_name]

    base_name = model_name.split(":")[0] if ":" in model_name else ""
    if base_name and base_name in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[base_name]

    return default


# ---------------------------------------------------------------------------
# Budget computation
# ---------------------------------------------------------------------------

def compute_budget(
    model_context_window: int,
    system_prompt: str,
    user_prompt: str,
    output_reserve: int = 2048,
) -> int:
    """Return the number of tokens available for entity context.

    Subtracts the system prompt (without context), user prompt, and an
    output reserve from the model's total context window.  Returns at
    least 0.
    """
    used = estimate_tokens(system_prompt) + estimate_tokens(user_prompt) + output_reserve
    return max(0, model_context_window - used)


# ---------------------------------------------------------------------------
# Three-tier context builder
# ---------------------------------------------------------------------------

# Approximate per-entity token costs
_TIER1_TOKENS_PER_ENTITY = 20   # full: "- `light.living_room` (Living Room Light) [Sala de Estar]"
_TIER2_TOKENS_PER_ENTITY = 10   # compact: "- `light.kitchen` [Cozinha]"
_TIER3_TOKENS_OVERHEAD = 30     # summary: "+ 45 sensor, 12 binary_sensor entities in other areas"


def build_tiered_context(
    entities: list[EntityEntry],
    areas: list[AreaEntry],
    budget_tokens: int,
) -> str:
    """Build entity context that fits within *budget_tokens*.

    Three tiers:
      1. **Full** — ``- `entity_id` (Friendly Name) [Area Name]``
      2. **Compact** — ``- `entity_id` [Area Name]``
      3. **Summary** — ``+ 45 sensor, 12 binary_sensor entities in other areas``

    Entities are consumed in order (the caller should pre-sort by relevance).
    When the budget is exhausted, remaining entities collapse into a domain
    count summary.
    """
    if not entities:
        return "## Available Entities\n\nNo entities available."

    area_map = {a.area_id: a.name for a in areas}
    lines: list[str] = ["## Available Entities"]
    tokens_used = estimate_tokens(lines[0])

    tier1_count = 0
    tier2_count = 0
    remaining: list[EntityEntry] = []

    # Tier 1: full detail
    for entity in entities:
        cost = _TIER1_TOKENS_PER_ENTITY
        if tokens_used + cost > budget_tokens:
            remaining = entities[tier1_count:]
            break
        area_name = area_map.get(entity.area_id, "Unassigned") if entity.area_id else "Unassigned"
        display = entity.name or entity.entity_id
        lines.append(f"- `{entity.entity_id}` ({display}) [{area_name}]")
        tokens_used += cost
        tier1_count += 1
    else:
        # All entities fit in tier 1
        return "\n".join(lines)

    # Tier 2: compact (remaining entities)
    tier2_start = len(remaining)
    compact_entities: list[EntityEntry] = []
    leftover: list[EntityEntry] = []

    for i, entity in enumerate(remaining):
        cost = _TIER2_TOKENS_PER_ENTITY
        if tokens_used + cost + _TIER3_TOKENS_OVERHEAD > budget_tokens:
            leftover = remaining[i:]
            break
        area_name = area_map.get(entity.area_id, "Unassigned") if entity.area_id else "Unassigned"
        lines.append(f"- `{entity.entity_id}` [{area_name}]")
        tokens_used += cost
        tier2_count += 1
    else:
        # All remaining fit in tier 2
        leftover = []

    # Tier 3: domain summary for anything that didn't fit
    if leftover:
        domain_counts: dict[str, int] = defaultdict(int)
        for entity in leftover:
            domain_counts[entity.domain] += 1

        parts = [f"{count} {domain}" for domain, count in sorted(domain_counts.items(), key=lambda x: -x[1])]
        summary = ", ".join(parts)
        lines.append(f"\n+ {summary} entities in other areas")

    return "\n".join(lines)
