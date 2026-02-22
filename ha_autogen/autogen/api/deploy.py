"""Deploy and rollback API endpoints."""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from ruamel.yaml import YAML

from autogen.db.database import Database
from autogen.deployer.dashboard_engine import DashboardDeployEngine, _sanitize_url_path
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
    target: str = Field(
        "new",
        description="Deploy target: 'new' to create a new dashboard, "
        "null/empty for default, or a url_path for an existing dashboard",
    )
    new_title: str = Field(
        "",
        description="Title for a new dashboard (used when target='new')",
    )


class DashboardDeployResponse(BaseModel):
    success: bool
    deployment_id: str = ""
    views_count: int = 0
    url_path: str | None = None
    message: str = ""


class DashboardListEntry(BaseModel):
    url_path: str | None = None
    title: str = ""
    icon: str = "mdi:view-dashboard"


class RollbackRequest(BaseModel):
    deployment_id: str = Field(..., description="Deployment ID to rollback")


class RollbackResponse(BaseModel):
    success: bool
    message: str = ""


@router.get("/dashboards", response_model=list[DashboardListEntry])
async def list_dashboards() -> list[DashboardListEntry]:
    """List all available Lovelace dashboards."""
    engine = DashboardDeployEngine()
    try:
        dashboards = await engine.list_dashboards()
    except Exception as e:
        logger.error("Failed to list dashboards: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    return [
        DashboardListEntry(
            url_path=d.get("url_path"),
            title=d.get("title", d.get("url_path") or "Default Dashboard"),
            icon=d.get("icon", "mdi:view-dashboard"),
        )
        for d in dashboards
    ]


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
    """Deploy a Lovelace dashboard config to Home Assistant.

    The ``target`` field controls where the dashboard is deployed:
    - ``"new"`` (default): Create a brand-new dashboard. Uses ``new_title``
      for the dashboard title (falls back to "AutoGen Dashboard").
    - ``""`` or ``null``: Deploy to the default (Overview) dashboard.
    - Any other string: Deploy to the existing dashboard with that url_path.
    """
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

    # Determine target url_path
    target = (body.target or "").strip()
    url_path: str | None = None
    created_new = False

    if target == "new":
        # Create a new dashboard first
        title = body.new_title.strip() if body.new_title else ""
        if not title:
            title = "AutoGen Dashboard"
        url_path = _sanitize_url_path(title)

        try:
            await engine.create_dashboard(
                url_path=url_path,
                title=title,
                icon="mdi:robot",
                show_in_sidebar=True,
            )
            created_new = True
        except RuntimeError as e:
            # If dashboard already exists with this url_path, just deploy to it
            err_msg = str(e).lower()
            if "already" in err_msg or "exists" in err_msg or "unique" in err_msg:
                logger.info("Dashboard %s already exists, deploying to it", url_path)
            else:
                raise HTTPException(status_code=500, detail=str(e))
    elif target:
        # Deploy to a specific existing dashboard
        url_path = target
    # else: url_path stays None → default dashboard

    try:
        result = await engine.deploy(config, url_path=url_path)
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

    msg = f"Dashboard deployed with {result['views_count']} view(s)"
    if created_new:
        msg += f" to new dashboard '{url_path}'"
    elif url_path:
        msg += f" to dashboard '{url_path}'"
    else:
        msg += " to default dashboard"

    return DashboardDeployResponse(
        success=True,
        deployment_id=deployment_id,
        views_count=result["views_count"],
        url_path=url_path,
        message=msg,
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
