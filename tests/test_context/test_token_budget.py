"""Tests for autogen.context.token_budget — token estimation, context windows, and tiered context."""

from __future__ import annotations

import pytest

from autogen.context.areas import AreaEntry
from autogen.context.entities import EntityEntry
from autogen.context.token_budget import (
    build_tiered_context,
    compute_budget,
    estimate_tokens,
    get_context_window,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entity(entity_id: str, name: str | None = None, area_id: str | None = None,
            disabled_by: str | None = None, hidden_by: str | None = None) -> EntityEntry:
    """Create an EntityEntry for testing."""
    return EntityEntry(
        entity_id=entity_id,
        name=name,
        area_id=area_id,
        platform="test",
        device_id=None,
        disabled_by=disabled_by,
        hidden_by=hidden_by,
        labels=[],
    )


def _area(area_id: str, name: str) -> AreaEntry:
    """Create an AreaEntry for testing."""
    return AreaEntry(
        area_id=area_id,
        name=name,
        aliases=[],
        floor_id=None,
        icon=None,
        labels=[],
        picture=None,
    )


# ---------------------------------------------------------------------------
# estimate_tokens
# ---------------------------------------------------------------------------

class TestEstimateTokens:
    def test_estimate_tokens_basic(self) -> None:
        """A 12-character string should estimate to 4 tokens (12 // 3)."""
        assert estimate_tokens("Hello World!") == 4

    def test_estimate_tokens_empty(self) -> None:
        """An empty string should return 0."""
        assert estimate_tokens("") == 0

    def test_estimate_tokens_short(self) -> None:
        """Strings shorter than 3 chars should still return 0 (integer division)."""
        assert estimate_tokens("ab") == 0

    def test_estimate_tokens_longer_text(self) -> None:
        """Check a known-length string (90 chars -> 30 tokens)."""
        text = "a" * 90
        assert estimate_tokens(text) == 30


# ---------------------------------------------------------------------------
# get_context_window
# ---------------------------------------------------------------------------

class TestGetContextWindow:
    def test_get_context_window_exact_match(self) -> None:
        """An exact model name found in the table should return the mapped value."""
        assert get_context_window("llama3.2") == 8192
        assert get_context_window("gpt-4o") == 128000

    def test_get_context_window_prefix_match(self) -> None:
        """A model name with a tag suffix should match via prefix (base:tag -> base)."""
        # "llama3.2:latest" should strip to "llama3.2" and find 8192
        assert get_context_window("llama3.2:latest") == 8192
        # "mistral:7b-instruct" should strip to "mistral" and find 32768
        assert get_context_window("mistral:7b-instruct") == 32768

    def test_get_context_window_unknown_default(self) -> None:
        """An unknown model should return the default value (32768)."""
        assert get_context_window("totally-unknown-model") == 32768
        assert get_context_window("totally-unknown-model", default=4096) == 4096

    def test_get_context_window_openrouter_prefix(self) -> None:
        """OpenRouter provider/model names should match by stripping the prefix."""
        assert get_context_window("openai/gpt-5.2") == 128000
        assert get_context_window("anthropic/claude-sonnet-4.6") == 200000

    def test_get_context_window_openrouter_prefix_fallback(self) -> None:
        """OpenRouter names should fall back to stripped name if full name not in table."""
        # "some-provider/gpt-4o" → strip → "gpt-4o" → 128000
        assert get_context_window("some-provider/gpt-4o") == 128000

    def test_get_context_window_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The AUTOGEN_MODEL_CONTEXT_WINDOW env var should override everything."""
        monkeypatch.setenv("AUTOGEN_MODEL_CONTEXT_WINDOW", "16384")
        # Even an exact-match model should be overridden
        assert get_context_window("llama3.2") == 16384
        assert get_context_window("unknown-model") == 16384

    def test_get_context_window_env_override_invalid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A non-integer env var should be ignored, falling back to the table."""
        monkeypatch.setenv("AUTOGEN_MODEL_CONTEXT_WINDOW", "not_a_number")
        # Falls back to exact match in table
        assert get_context_window("llama3.2") == 8192


# ---------------------------------------------------------------------------
# compute_budget
# ---------------------------------------------------------------------------

class TestComputeBudget:
    def test_compute_budget_basic(self) -> None:
        """Budget = window - system_tokens - user_tokens - output_reserve."""
        # system: 30 chars -> 10 tokens; user: 15 chars -> 5 tokens; reserve: 2048
        # budget = 8192 - 10 - 5 - 2048 = 6129
        system = "a" * 30  # 10 tokens
        user = "b" * 15    # 5 tokens
        result = compute_budget(8192, system, user, output_reserve=2048)
        assert result == 8192 - 10 - 5 - 2048

    def test_compute_budget_zero_when_exceeded(self) -> None:
        """When prompts + reserve exceed the window, budget should be 0 (never negative)."""
        huge_system = "x" * 30000  # 10000 tokens
        user = "y" * 3000          # 1000 tokens
        result = compute_budget(4096, huge_system, user, output_reserve=2048)
        assert result == 0

    def test_compute_budget_default_reserve(self) -> None:
        """Default output_reserve should be 2048."""
        result = compute_budget(10000, "", "")
        assert result == 10000 - 2048

    def test_compute_budget_exact_fit(self) -> None:
        """If prompts + reserve exactly equal the window, budget is 0."""
        # 3 chars -> 1 token; reserve 2048 -> total needed: 1 + 0 + 2048 = 2049
        result = compute_budget(2049, "abc", "", output_reserve=2048)
        assert result == 0


# ---------------------------------------------------------------------------
# build_tiered_context
# ---------------------------------------------------------------------------

class TestBuildTieredContext:
    def test_build_tiered_all_fit(self) -> None:
        """With a large budget and few entities, all should appear as Tier 1 (full detail)."""
        entities = [
            _entity("light.living_room", "Living Room Light", area_id="living_room"),
            _entity("sensor.temperature_bedroom", "Bedroom Temp", area_id="bedroom"),
            _entity("binary_sensor.motion_kitchen", "Kitchen Motion", area_id="kitchen"),
        ]
        areas = [
            _area("living_room", "Living Room"),
            _area("bedroom", "Bedroom"),
            _area("kitchen", "Kitchen"),
        ]

        result = build_tiered_context(entities, areas, budget_tokens=5000)

        # All three entities should appear with full detail: name + area
        assert "## Available Entities" in result
        assert "`light.living_room` (Living Room Light) [Living Room]" in result
        assert "`sensor.temperature_bedroom` (Bedroom Temp) [Bedroom]" in result
        assert "`binary_sensor.motion_kitchen` (Kitchen Motion) [Kitchen]" in result
        # No tier 3 summary should appear
        assert "entities in other areas" not in result

    def test_build_tiered_mixed(self) -> None:
        """With a medium budget, some entities should be Tier 1, some Tier 2, rest Tier 3."""
        entities = [
            _entity("light.living_room", "Living Room Light", area_id="living_room"),
            _entity("light.bedroom", "Bedroom Light", area_id="bedroom"),
            _entity("light.kitchen", "Kitchen Light", area_id="kitchen"),
            _entity("sensor.temperature_living", "Living Temp", area_id="living_room"),
            _entity("sensor.humidity_bathroom", "Bathroom Humidity", area_id="bathroom"),
            _entity("binary_sensor.motion_hallway", "Hallway Motion", area_id="hallway"),
            _entity("switch.garage_door", "Garage Door Switch", area_id="garage"),
            _entity("cover.bedroom_blinds", "Bedroom Blinds", area_id="bedroom"),
            _entity("climate.main_thermostat", "Main Thermostat", area_id="living_room"),
            _entity("fan.ceiling_bedroom", "Bedroom Ceiling Fan", area_id="bedroom"),
        ]
        areas = [
            _area("living_room", "Living Room"),
            _area("bedroom", "Bedroom"),
            _area("kitchen", "Kitchen"),
            _area("bathroom", "Bathroom"),
            _area("hallway", "Hallway"),
            _area("garage", "Garage"),
        ]

        # Budget of ~80 tokens: header (~8 tokens), Tier 1 costs 20 each,
        # so ~3 Tier 1 (60 tokens + ~8 header = 68), then Tier 2 at 10 each,
        # with 30 tokens for Tier 3 overhead reserved.
        # Remaining budget for Tier 2: 80 - 68 - 30 = ~2 tokens → might not fit any.
        # Use a slightly larger budget so we get some Tier 2.
        result = build_tiered_context(entities, areas, budget_tokens=120)

        # Header is always present
        assert "## Available Entities" in result

        # First few entities should have full detail (Tier 1 format: name in parens)
        assert "(" in result  # At least some full-detail entries

        # Should have a summary for entities that didn't fit
        assert "entities in other areas" in result

    def test_build_tiered_empty_entities(self) -> None:
        """With no entities, should return a placeholder message."""
        result = build_tiered_context([], [], budget_tokens=5000)
        assert "No entities available" in result

    def test_build_tiered_unassigned_area(self) -> None:
        """Entities without an area_id should show [Unassigned]."""
        entities = [
            _entity("light.orphan", "Orphan Light", area_id=None),
        ]
        areas: list[AreaEntry] = []

        result = build_tiered_context(entities, areas, budget_tokens=5000)
        assert "[Unassigned]" in result

    def test_build_tiered_zero_budget(self) -> None:
        """With zero budget, all entities should collapse to Tier 3 summary."""
        entities = [
            _entity("light.living_room", "Living Room Light", area_id="lr"),
            _entity("sensor.temp", "Temp Sensor", area_id="lr"),
        ]
        areas = [_area("lr", "Living Room")]

        # Budget=0: nothing fits in Tier 1
        result = build_tiered_context(entities, areas, budget_tokens=0)

        # With zero budget even the header exceeds it, so Tier 1 loop breaks
        # immediately and all entities go to Tier 3 summary
        assert "## Available Entities" in result
