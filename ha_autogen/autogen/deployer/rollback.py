"""Rollback to a previous backup."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from autogen.deployer.backup import create_backup

logger = logging.getLogger(__name__)


def rollback(backup_path: str, target_path: Path) -> None:
    """Restore a backup file to the target location.

    Creates a safety backup of the current state before overwriting.
    """
    source = Path(backup_path)
    if not source.exists():
        raise FileNotFoundError(f"Backup not found: {backup_path}")

    # Safety backup of current state before rollback
    if target_path.exists():
        create_backup(target_path)

    shutil.copy2(source, target_path)
    logger.info("Rolled back %s from backup %s", target_path, backup_path)
