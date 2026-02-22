"""Review engine — combines deterministic rules with LLM analysis."""

from __future__ import annotations

import json
import logging
import re
from io import StringIO

from ruamel.yaml import YAML

from autogen.llm.base import LLMBackend
from autogen.llm.prompts.dashboard_review import (
    DASHBOARD_REVIEW_SYSTEM_PROMPT,
    build_dashboard_review_user_prompt,
)
from autogen.llm.prompts.review import REVIEW_SYSTEM_PROMPT, build_review_user_prompt
from autogen.reviewer.automation_rules import run_all_rules
from autogen.reviewer.dashboard_rules import run_all_dashboard_rules
from autogen.reviewer.models import (
    FindingCategory,
    FindingSeverity,
    ReviewFinding,
    ReviewResult,
)

logger = logging.getLogger(__name__)

_yaml = YAML()
_yaml.default_flow_style = False


class ReviewEngine:
    """Orchestrates deterministic rules + LLM review of automations."""

    def __init__(self, llm_backend: LLMBackend) -> None:
        self._llm = llm_backend

    async def review_automations(
        self,
        automations: list[dict],
        entity_summary: str | None = None,
        extra_instructions: str | None = None,
    ) -> ReviewResult:
        """Run a full review on a list of automations.

        1. Run deterministic rules on each automation.
        2. Send all automations to LLM for semantic analysis.
        3. Merge and deduplicate findings.
        """
        # Phase 1: deterministic rules
        rule_findings: list[ReviewFinding] = []
        for automation in automations:
            rule_findings.extend(run_all_rules(automation))

        logger.info(
            "Deterministic rules produced %d findings for %d automations",
            len(rule_findings),
            len(automations),
        )

        # Phase 2: LLM analysis
        llm_findings: list[ReviewFinding] = []
        model = ""
        prompt_tokens = 0
        completion_tokens = 0

        try:
            automations_yaml = self._automations_to_yaml(automations)
            user_prompt = build_review_user_prompt(automations_yaml, entity_summary)

            system_prompt = REVIEW_SYSTEM_PROMPT
            if extra_instructions:
                system_prompt = f"{system_prompt}\n\n{extra_instructions}"
            llm_response = await self._llm.generate(
                system_prompt, user_prompt,
            )
            model = llm_response.model
            prompt_tokens = llm_response.prompt_tokens
            completion_tokens = llm_response.completion_tokens

            llm_findings = self._parse_llm_findings(llm_response.content)
            logger.info("LLM review produced %d findings", len(llm_findings))
        except Exception:
            logger.exception("LLM review failed, returning rule-based findings only")

        # Phase 3: merge and deduplicate
        all_findings = self._merge_findings(rule_findings, llm_findings)
        self._sort_findings(all_findings)

        # Build summary
        summary = self._build_summary(all_findings, len(automations))

        return ReviewResult(
            findings=all_findings,
            summary=summary,
            automations_reviewed=len(automations),
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    async def review_dashboards(
        self,
        dashboard: dict,
        known_entity_ids: set[str] | None = None,
        areas: list[dict] | None = None,
        entity_summary: str | None = None,
        extra_instructions: str | None = None,
    ) -> ReviewResult:
        """Run a full review on a Lovelace dashboard config.

        1. Run deterministic rules on the dashboard.
        2. Send the dashboard config to LLM for semantic analysis.
        3. Merge and deduplicate findings.
        """
        # Phase 1: deterministic rules
        rule_findings = run_all_dashboard_rules(dashboard, known_entity_ids, areas)
        logger.info(
            "Dashboard deterministic rules produced %d findings",
            len(rule_findings),
        )

        # Phase 2: LLM analysis
        llm_findings: list[ReviewFinding] = []
        model = ""
        prompt_tokens = 0
        completion_tokens = 0

        try:
            dashboard_yaml = self._dict_to_yaml(dashboard)
            user_prompt = build_dashboard_review_user_prompt(
                dashboard_yaml, entity_summary
            )

            dash_system_prompt = DASHBOARD_REVIEW_SYSTEM_PROMPT
            if extra_instructions:
                dash_system_prompt = f"{dash_system_prompt}\n\n{extra_instructions}"
            llm_response = await self._llm.generate(
                dash_system_prompt, user_prompt,
            )
            model = llm_response.model
            prompt_tokens = llm_response.prompt_tokens
            completion_tokens = llm_response.completion_tokens

            llm_findings = self._parse_llm_findings(llm_response.content)
            logger.info("LLM dashboard review produced %d findings", len(llm_findings))
        except Exception:
            logger.exception(
                "LLM dashboard review failed, returning rule-based findings only"
            )

        # Phase 3: merge and deduplicate
        all_findings = self._merge_findings(rule_findings, llm_findings)
        self._sort_findings(all_findings)

        views_count = len(dashboard.get("views", []))
        summary = self._build_dashboard_summary(all_findings, views_count)

        return ReviewResult(
            findings=all_findings,
            summary=summary,
            dashboards_reviewed=1,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    async def review_full(
        self,
        automations: list[dict],
        dashboard: dict,
        known_entity_ids: set[str] | None = None,
        areas: list[dict] | None = None,
        entity_summary: str | None = None,
        extra_instructions: str | None = None,
    ) -> ReviewResult:
        """Run a combined review of both automations and dashboards."""
        auto_result = await self.review_automations(
            automations, entity_summary, extra_instructions,
        )
        dash_result = await self.review_dashboards(
            dashboard, known_entity_ids, areas, entity_summary,
            extra_instructions,
        )

        all_findings = auto_result.findings + dash_result.findings
        self._sort_findings(all_findings)

        summary = (
            f"Full review: {auto_result.automations_reviewed} automation(s), "
            f"{dash_result.dashboards_reviewed} dashboard(s). "
            f"Found {len(all_findings)} total issue(s)."
        )

        return ReviewResult(
            findings=all_findings,
            summary=summary,
            automations_reviewed=auto_result.automations_reviewed,
            dashboards_reviewed=dash_result.dashboards_reviewed,
            model=auto_result.model or dash_result.model,
            prompt_tokens=auto_result.prompt_tokens + dash_result.prompt_tokens,
            completion_tokens=auto_result.completion_tokens + dash_result.completion_tokens,
        )

    def _automations_to_yaml(self, automations: list[dict]) -> str:
        """Convert automation dicts to a YAML string."""
        buf = StringIO()
        _yaml.dump(automations, buf)
        return buf.getvalue()

    def _dict_to_yaml(self, data: dict) -> str:
        """Convert a dict to a YAML string."""
        buf = StringIO()
        _yaml.dump(data, buf)
        return buf.getvalue()

    @staticmethod
    def _sort_findings(findings: list[ReviewFinding]) -> None:
        """Sort findings by severity: critical → warning → suggestion → info."""
        severity_order = {
            FindingSeverity.critical: 0,
            FindingSeverity.warning: 1,
            FindingSeverity.suggestion: 2,
            FindingSeverity.info: 3,
        }
        findings.sort(key=lambda f: severity_order.get(f.severity, 99))

    def _build_dashboard_summary(
        self, findings: list[ReviewFinding], views_count: int,
    ) -> str:
        """Build a human-readable summary of dashboard findings."""
        if not findings:
            return f"Reviewed dashboard with {views_count} view(s) — no issues found."

        counts: dict[str, int] = {}
        for f in findings:
            counts[f.severity.value] = counts.get(f.severity.value, 0) + 1

        parts = [
            f"Reviewed dashboard with {views_count} view(s), "
            f"found {len(findings)} issue(s): "
        ]
        severity_labels = []
        for sev in ("critical", "warning", "suggestion", "info"):
            if sev in counts:
                severity_labels.append(f"{counts[sev]} {sev}")
        parts.append(", ".join(severity_labels) + ".")

        return "".join(parts)

    def _parse_llm_findings(self, content: str) -> list[ReviewFinding]:
        """Parse LLM response content into ReviewFinding objects."""
        # Extract JSON from code fences
        match = re.search(r"```(?:json)?\s*\n(.*?)```", content, re.DOTALL)
        if not match:
            logger.warning("No JSON code fence found in LLM review response")
            return []

        try:
            raw = json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM review JSON")
            return []

        if not isinstance(raw, list):
            raw = [raw]

        findings: list[ReviewFinding] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                finding = ReviewFinding(
                    severity=FindingSeverity(item.get("severity", "info")),
                    category=FindingCategory(
                        item.get("category", "error_resilience")
                    ),
                    automation_id=item.get("automation_id", ""),
                    automation_alias=item.get("automation_alias", ""),
                    title=item.get("title", "Untitled finding"),
                    description=item.get("description", ""),
                    current_yaml=item.get("current_yaml"),
                    suggested_yaml=item.get("suggested_yaml"),
                )
                findings.append(finding)
            except (ValueError, KeyError) as e:
                logger.warning("Skipping invalid LLM finding: %s", e)

        return findings

    def _merge_findings(
        self,
        rule_findings: list[ReviewFinding],
        llm_findings: list[ReviewFinding],
    ) -> list[ReviewFinding]:
        """Merge rule-based and LLM findings, removing duplicates."""
        # Use (automation_id, category, title_prefix) as dedup key
        seen: set[tuple[str, str, str]] = set()
        merged: list[ReviewFinding] = []

        # Rule-based findings take priority
        for f in rule_findings:
            key = (f.automation_id, f.category.value, f.title[:30])
            seen.add(key)
            merged.append(f)

        # Add non-duplicate LLM findings
        for f in llm_findings:
            key = (f.automation_id, f.category.value, f.title[:30])
            if key not in seen:
                seen.add(key)
                merged.append(f)

        return merged

    def _build_summary(self, findings: list[ReviewFinding], total: int) -> str:
        """Build a human-readable summary of findings."""
        if not findings:
            return f"Reviewed {total} automation(s) — no issues found."

        counts = {}
        for f in findings:
            counts[f.severity.value] = counts.get(f.severity.value, 0) + 1

        parts = [f"Reviewed {total} automation(s), found {len(findings)} issue(s): "]
        severity_labels = []
        for sev in ("critical", "warning", "suggestion", "info"):
            if sev in counts:
                severity_labels.append(f"{counts[sev]} {sev}")
        parts.append(", ".join(severity_labels) + ".")

        return "".join(parts)
