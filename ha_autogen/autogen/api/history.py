"""History API endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from autogen.db.database import Database
from autogen.deps import get_database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["history"])


class HistoryListItem(BaseModel):
    id: str
    request: str
    model: str = ""
    status: str = "draft"
    type: str = "automation"
    created_at: str = ""


class HistoryListResponse(BaseModel):
    items: list[HistoryListItem]
    total: int


class HistoryDetailResponse(BaseModel):
    id: str
    request: str
    yaml_output: str
    raw_response: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    validation_json: str = "{}"
    retries: int = 0
    status: str = "draft"
    type: str = "automation"
    created_at: str = ""
    updated_at: str = ""


@router.get("/history", response_model=HistoryListResponse)
async def list_history(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_database),
) -> HistoryListResponse:
    """List generation history, newest first."""
    async with db.conn.execute(
        "SELECT COUNT(*) as cnt FROM generations"
    ) as cursor:
        row = await cursor.fetchone()
        total = row["cnt"]

    async with db.conn.execute(
        "SELECT id, request, model, status, type, created_at "
        "FROM generations ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ) as cursor:
        rows = await cursor.fetchall()

    items = [
        HistoryListItem(
            id=r["id"],
            request=r["request"],
            model=r["model"],
            status=r["status"],
            type=r["type"] or "automation",
            created_at=r["created_at"],
        )
        for r in rows
    ]
    return HistoryListResponse(items=items, total=total)


@router.get("/history/{generation_id}", response_model=HistoryDetailResponse)
async def get_history_item(
    generation_id: str,
    db: Database = Depends(get_database),
) -> HistoryDetailResponse:
    """Get a single generation record."""
    async with db.conn.execute(
        "SELECT * FROM generations WHERE id = ?", (generation_id,)
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Generation not found")

    return HistoryDetailResponse(**dict(row))


@router.delete("/history/{generation_id}")
async def delete_history_item(
    generation_id: str,
    db: Database = Depends(get_database),
) -> dict:
    """Delete a generation record."""
    await db.conn.execute("DELETE FROM generations WHERE id = ?", (generation_id,))
    await db.conn.commit()
    return {"deleted": True}
