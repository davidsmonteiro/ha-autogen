"""Batch application of Quick Fixes."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from autogen.quickfix.classifier import EnrichedFinding, FixClassification

logger = logging.getLogger(__name__)


class FixApplicationResult(BaseModel):
    """Result of applying a single fix."""

    finding_id: str = ""
    finding_title: str
    automation_id: str = ""
    success: bool
    error: str = ""


class BatchResult(BaseModel):
    """Result of a batch fix application."""

    total: int
    applied: int
    failed: int
    results: list[FixApplicationResult] = Field(default_factory=list)


async def apply_batch(
    enriched_findings: list[EnrichedFinding],
    confirmed_sensitive: set[str] | None = None,
    deploy_fn=None,
) -> BatchResult:
    """Apply all Quick Fix findings in sequence.

    Args:
        enriched_findings: Findings to process (only QUICK with fix_yaml applied).
        confirmed_sensitive: Set of finding_ids the user explicitly confirmed
                             for sensitive-domain fixes.
        deploy_fn: Async callable(automation_id, fix_yaml) -> None.
                   Raises on failure.
    """
    if confirmed_sensitive is None:
        confirmed_sensitive = set()

    quick_fixes = [
        ef for ef in enriched_findings
        if ef.fix_type == FixClassification.QUICK and ef.fix_yaml is not None
    ]

    results: list[FixApplicationResult] = []

    for ef in quick_fixes:
        fid = ef.finding.finding_id
        aid = ef.finding.automation_id

        # Skip unconfirmed sensitive fixes
        if ef.requires_confirmation and fid not in confirmed_sensitive:
            results.append(
                FixApplicationResult(
                    finding_id=fid,
                    finding_title=ef.finding.title,
                    automation_id=aid,
                    success=False,
                    error="Sensitive domain fix not confirmed",
                )
            )
            continue

        try:
            if deploy_fn:
                await deploy_fn(aid, ef.fix_yaml)
            results.append(
                FixApplicationResult(
                    finding_id=fid,
                    finding_title=ef.finding.title,
                    automation_id=aid,
                    success=True,
                )
            )
        except Exception as e:
            logger.warning("Failed to apply fix for %s: %s", aid, e)
            results.append(
                FixApplicationResult(
                    finding_id=fid,
                    finding_title=ef.finding.title,
                    automation_id=aid,
                    success=False,
                    error=str(e),
                )
            )

    return BatchResult(
        total=len(quick_fixes),
        applied=sum(1 for r in results if r.success),
        failed=sum(1 for r in results if not r.success),
        results=results,
    )
