"""Pre-deploy backup snapshots."""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_backup_dir() -> Path:
    """Return the backup storage directory."""
    if os.environ.get("AUTOGEN_DEV_MODE", "").lower() == "true":
        backup_dir = (
            Path(__file__).resolve().parent.parent.parent.parent / "tests" / "output" / "backups"
        )
    else:
        backup_dir = Path("/data/backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def create_backup(file_path: Path) -> Path:
    """Create a timestamped backup copy of the given file.

    Returns the path to the backup file.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Cannot backup: {file_path} does not exist")

    backup_dir = _get_backup_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{file_path.stem}_{timestamp}{file_path.suffix}"
    backup_path = backup_dir / backup_name

    shutil.copy2(file_path, backup_path)
    logger.info("Backup created: %s", backup_path)
    return backup_path


def list_backups() -> list[dict]:
    """List all available backups, newest first."""
    backup_dir = _get_backup_dir()
    backups = []
    for f in sorted(backup_dir.glob("*.yaml"), reverse=True):
        backups.append({
            "path": str(f),
            "name": f.name,
            "size": f.stat().st_size,
            "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    return backups
