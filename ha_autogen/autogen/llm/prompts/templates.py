"""User-defined prompt templates — DB-backed CRUD + prompt injection."""

from __future__ import annotations

import re
import uuid
from typing import Literal

import aiosqlite
from pydantic import BaseModel, Field


# Max content length per template (chars)
MAX_TEMPLATE_CONTENT = 2000


class PromptTemplate(BaseModel):
    """A user-defined prompt addition."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    content: str
    target: Literal["system", "automation", "dashboard", "review"] = "system"
    position: Literal["prepend", "append"] = "append"
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""


class TemplateStore:
    """DB-backed CRUD store for prompt templates."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def list_templates(self) -> list[PromptTemplate]:
        """Return all templates, ordered by name."""
        async with self._conn.execute(
            "SELECT * FROM prompt_templates ORDER BY name"
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_template(r) for r in rows]

    async def get_template(self, template_id: str) -> PromptTemplate | None:
        """Return a single template by ID, or None."""
        async with self._conn.execute(
            "SELECT * FROM prompt_templates WHERE id = ?", (template_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return self._row_to_template(row) if row else None

    async def create_template(self, template: PromptTemplate) -> PromptTemplate:
        """Insert a new template and return it."""
        template.content = _sanitize_content(template.content)
        if not template.id:
            template.id = uuid.uuid4().hex
        await self._conn.execute(
            """INSERT INTO prompt_templates
               (id, name, content, target, position, enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
            (
                template.id,
                template.name,
                template.content,
                template.target,
                template.position,
                1 if template.enabled else 0,
            ),
        )
        await self._conn.commit()
        return await self.get_template(template.id)  # type: ignore[return-value]

    async def update_template(
        self, template_id: str, updates: dict,
    ) -> PromptTemplate | None:
        """Update fields on an existing template."""
        existing = await self.get_template(template_id)
        if not existing:
            return None

        if "content" in updates:
            updates["content"] = _sanitize_content(updates["content"])

        allowed = {"name", "content", "target", "position", "enabled"}
        sets: list[str] = []
        values: list = []
        for key, val in updates.items():
            if key not in allowed:
                continue
            if key == "enabled":
                val = 1 if val else 0
            sets.append(f"{key} = ?")
            values.append(val)

        if not sets:
            return existing

        sets.append("updated_at = datetime('now')")
        values.append(template_id)
        await self._conn.execute(
            f"UPDATE prompt_templates SET {', '.join(sets)} WHERE id = ?",
            values,
        )
        await self._conn.commit()
        return await self.get_template(template_id)

    async def delete_template(self, template_id: str) -> bool:
        """Delete a template. Returns True if it existed."""
        cursor = await self._conn.execute(
            "DELETE FROM prompt_templates WHERE id = ?", (template_id,)
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def get_active_templates(
        self, target: str,
    ) -> list[PromptTemplate]:
        """Return enabled templates for a given target, ordered by name."""
        async with self._conn.execute(
            "SELECT * FROM prompt_templates WHERE enabled = 1 AND target = ? ORDER BY name",
            (target,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_template(r) for r in rows]

    @staticmethod
    def _row_to_template(row: aiosqlite.Row) -> PromptTemplate:
        return PromptTemplate(
            id=row["id"],
            name=row["name"],
            content=row["content"],
            target=row["target"],
            position=row["position"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
        )


def _sanitize_content(content: str) -> str:
    """Strip code fences and enforce max length."""
    # Remove markdown code fences
    content = re.sub(r"```[\w]*\n?", "", content)
    content = content.strip()
    return content[:MAX_TEMPLATE_CONTENT]


def apply_templates(base_prompt: str, templates: list[PromptTemplate]) -> str:
    """Apply a list of templates to a base prompt via prepend/append."""
    prepends: list[str] = []
    appends: list[str] = []

    for t in templates:
        if t.position == "prepend":
            prepends.append(t.content)
        else:
            appends.append(t.content)

    parts: list[str] = []
    if prepends:
        parts.extend(prepends)
    parts.append(base_prompt)
    if appends:
        parts.extend(appends)

    return "\n\n".join(parts)
