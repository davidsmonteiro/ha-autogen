"""Deploy and rollback API endpoints."""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from ruamel.yaml import YAML

from autogen.db.database import Database
from autogen.deployer.dashboard_engine import DashboardDeployEngine
from autogen.deployer.engine import DeployEngine
from autogen.deployer.rollback import rollback as perform_rollback
from autogen.deps import get_database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["deploy"])


class DeployRequest(BaseModel):
    generation_id: str | None = Field(None, description="ID of the generation to deploy")
    yaml_content: str = Field(..., min_length=10, description="YAML content to deploy")


class DeployResponse(BaseModel):
    success: bool
    deployment_id: str = ""
    automation_id: str = ""
    backup_path: str | None = None
    message: str = ""


class DashboardDeployRequest(BaseModel):
    generation_id: str | None = Field(None, description="ID of the generation to deploy")
    yaml_content: str = Field(..., min_length=10, description="YAML content of the dashboard config")


class DashboardDeployResponse(BaseModel):
    success: bool
    deployment_id: str = ""
    views_count: int = 0
    message: str = ""


class RollbackRequest(BaseModel):
    deployment_id: str = Field(..., description="Deployment ID to rollback")


class RollbackResponse(BaseModel):
    success: bool
    message: str = ""


@router.post("/deploy", response_model=DeployResponse)
async def deploy_automation(
    body: DeployRequest,
    db: Database = Depends(get_database),
) -> DeployResponse:
    """Deploy an automation to Home Assistant."""
    engine = DeployEngine()

    try:
        result = await engine.deploy(body.yaml_content)
    except Exception as e:
        logger.error("Deploy failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    # Record in DB
    deployment_id = uuid.uuid4().hex
    await db.conn.execute(
        """INSERT INTO deployments
           (id, generation_id, automation_id, yaml_deployed, backup_path, status)
           VALUES (?, ?, ?, ?, ?, 'deployed')""",
        (
            deployment_id,
            body.generation_id or "",
            result["automation_id"],
            body.yaml_content,
            result.get("backup_path"),
        ),
    )

    # Update generation status if linked
    if body.generation_id:
        await db.conn.execute(
            "UPDATE generations SET status = 'deployed', updated_at = datetime('now') "
            "WHERE id = ?",
            (body.generation_id,),
        )

    await db.conn.commit()

    return DeployResponse(
        success=True,
        deployment_id=deployment_id,
        automation_id=result["automation_id"],
        backup_path=result.get("backup_path"),
        message="Automation deployed successfully"
        + (" (replaced existing)" if result.get("replaced") else " (appended)"),
    )


@router.post("/deploy-dashboard", response_model=DashboardDeployResponse)
async def deploy_dashboard(
    body: DashboardDeployRequest,
    db: Database = Depends(get_database),
) -> DashboardDeployResponse:
    """Deploy a Lovelace dashboard config to Home Assistant."""
    # Parse YAML content into a dict
    yaml_parser = YAML()
    try:
        from io import StringIO
        config = yaml_parser.load(StringIO(body.yaml_content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")

    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="Dashboard config must be a YAML mapping")

    engine = DashboardDeployEngine()

    try:
        result = await engine.deploy(config)
    except Exception as e:
        logger.error("Dashboard deploy failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    # Record in DB
    deployment_id = uuid.uuid4().hex
    await db.conn.execute(
        """INSERT INTO deployments
           (id, generation_id, yaml_deployed, backup_path, status, type)
           VALUES (?, ?, ?, ?, 'deployed', 'dashboard')""",
        (
            deployment_id,
            body.generation_id or "",
            body.yaml_content,
            result.get("backup_json"),
        ),
    )

    # Update generation status if linked
    if body.generation_id:
        await db.conn.execute(
            "UPDATE generations SET status = 'deployed', updated_at = datetime('now') "
            "WHERE id = ?",
            (body.generation_id,),
        )

    await db.conn.commit()

    return DashboardDeployResponse(
        success=True,
        deployment_id=deployment_id,
        views_count=result["views_count"],
        message=f"Dashboard deployed with {result['views_count']} view(s)",
    )


@router.post("/rollback", response_model=RollbackResponse)
async def rollback_deployment(
    body: RollbackRequest,
    db: Database = Depends(get_database),
) -> RollbackResponse:
    """Rollback a deployment to the previous backup."""
    async with db.conn.execute(
        "SELECT * FROM deployments WHERE id = ?", (body.deployment_id,)
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Deployment not found")

    backup_path = row["backup_path"]
    if not backup_path:
        raise HTTPException(status_code=400, detail="No backup available for this deployment")

    engine = DeployEngine()
    try:
        perform_rollback(backup_path, engine.automations_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Backup file not found")

    # Update records
    await db.conn.execute(
        "UPDATE deployments SET status = 'rolled_back', "
        "rolled_back_at = datetime('now') WHERE id = ?",
        (body.deployment_id,),
    )

    generation_id = row["generation_id"]
    if generation_id:
        await db.conn.execute(
            "UPDATE generations SET status = 'rolled_back', "
            "updated_at = datetime('now') WHERE id = ?",
            (generation_id,),
        )

    await db.conn.commit()

    # Trigger HA reload if not dev mode
    if not engine._dev_mode:
        await engine._trigger_reload()

    return RollbackResponse(
        success=True,
        message="Rolled back successfully. Previous state restored.",
    )
