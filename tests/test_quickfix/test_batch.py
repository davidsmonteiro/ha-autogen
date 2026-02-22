"""Tests for quickfix batch application."""

from __future__ import annotations

import pytest

from autogen.quickfix.batch import BatchResult, apply_batch
from autogen.quickfix.classifier import EnrichedFinding, FixClassification
from autogen.reviewer.models import FindingCategory, FindingSeverity, ReviewFinding


def _enriched(
    fix_type: FixClassification = FixClassification.QUICK,
    fix_yaml: str | None = "service: light.turn_on",
    requires_confirmation: bool = False,
    finding_id: str = "f1",
    automation_id: str = "a1",
    title: str = "Test fix",
) -> EnrichedFinding:
    return EnrichedFinding(
        finding=ReviewFinding(
            finding_id=finding_id,
            severity=FindingSeverity.suggestion,
            category=FindingCategory.deprecated_patterns,
            automation_id=automation_id,
            title=title,
            description="Test description",
        ),
        fix_type=fix_type,
        fix_yaml=fix_yaml,
        requires_confirmation=requires_confirmation,
    )


class TestApplyBatch:
    @pytest.mark.asyncio
    async def test_apply_all_quick_fixes(self) -> None:
        deployed = []

        async def deploy(aid: str, yaml: str) -> None:
            deployed.append((aid, yaml))

        findings = [
            _enriched(finding_id="f1", automation_id="a1"),
            _enriched(finding_id="f2", automation_id="a2"),
        ]
        result = await apply_batch(findings, deploy_fn=deploy)
        assert result.total == 2
        assert result.applied == 2
        assert result.failed == 0
        assert len(deployed) == 2

    @pytest.mark.asyncio
    async def test_skips_guided_fixes(self) -> None:
        findings = [
            _enriched(fix_type=FixClassification.GUIDED, finding_id="f1"),
            _enriched(fix_type=FixClassification.QUICK, finding_id="f2"),
        ]
        result = await apply_batch(findings, deploy_fn=None)
        assert result.total == 1  # Only the QUICK one
        assert result.applied == 1

    @pytest.mark.asyncio
    async def test_skips_fixes_without_yaml(self) -> None:
        findings = [
            _enriched(fix_yaml=None, finding_id="f1"),
            _enriched(fix_yaml="service: x", finding_id="f2"),
        ]
        result = await apply_batch(findings, deploy_fn=None)
        assert result.total == 1  # Only the one with fix_yaml

    @pytest.mark.asyncio
    async def test_skips_unconfirmed_sensitive(self) -> None:
        findings = [
            _enriched(requires_confirmation=True, finding_id="f1"),
            _enriched(requires_confirmation=False, finding_id="f2"),
        ]
        result = await apply_batch(findings, confirmed_sensitive=set(), deploy_fn=None)
        assert result.total == 2
        assert result.applied == 1  # f2 only
        assert result.failed == 1  # f1 skipped
        assert result.results[0].error == "Sensitive domain fix not confirmed"

    @pytest.mark.asyncio
    async def test_confirmed_sensitive_is_applied(self) -> None:
        deployed = []

        async def deploy(aid: str, yaml: str) -> None:
            deployed.append(aid)

        findings = [
            _enriched(requires_confirmation=True, finding_id="f1"),
        ]
        result = await apply_batch(findings, confirmed_sensitive={"f1"}, deploy_fn=deploy)
        assert result.applied == 1
        assert len(deployed) == 1

    @pytest.mark.asyncio
    async def test_deploy_failure_handled(self) -> None:
        async def failing_deploy(aid: str, yaml: str) -> None:
            raise RuntimeError("Deploy failed")

        findings = [_enriched(finding_id="f1")]
        result = await apply_batch(findings, deploy_fn=failing_deploy)
        assert result.total == 1
        assert result.applied == 0
        assert result.failed == 1
        assert "Deploy failed" in result.results[0].error

    @pytest.mark.asyncio
    async def test_empty_findings(self) -> None:
        result = await apply_batch([], deploy_fn=None)
        assert result.total == 0
        assert result.applied == 0
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_no_deploy_fn_still_succeeds(self) -> None:
        """When deploy_fn is None, fixes are still 'applied' (noop)."""
        findings = [_enriched(finding_id="f1")]
        result = await apply_batch(findings, deploy_fn=None)
        assert result.total == 1
        assert result.applied == 1
