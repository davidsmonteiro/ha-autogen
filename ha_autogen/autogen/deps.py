"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import TYPE_CHECKING

from autogen.context.engine import ContextEngine
from autogen.llm.base import LLMBackend

if TYPE_CHECKING:
    from autogen.db.database import Database
    from autogen.explorer.engine import ExplorerEngine
    from autogen.llm.prompts.templates import TemplateStore
    from autogen.reviewer.engine import ReviewEngine

_context_engine: ContextEngine | None = None
_llm_backend: LLMBackend | None = None
_database: Database | None = None
_review_engine: ReviewEngine | None = None
_template_store: TemplateStore | None = None
_explorer_engine: ExplorerEngine | None = None


def get_context_engine() -> ContextEngine:
    """FastAPI dependency: return the shared ContextEngine."""
    assert _context_engine is not None, "ContextEngine not initialised"
    return _context_engine


def get_llm_backend() -> LLMBackend:
    """FastAPI dependency: return the shared LLMBackend."""
    assert _llm_backend is not None, "LLMBackend not initialised"
    return _llm_backend


def get_database() -> Database:
    """FastAPI dependency: return the shared Database."""
    from autogen.db.database import Database

    assert _database is not None, "Database not initialised"
    return _database


def get_review_engine() -> ReviewEngine:
    """FastAPI dependency: return the shared ReviewEngine."""
    from autogen.reviewer.engine import ReviewEngine

    assert _review_engine is not None, "ReviewEngine not initialised"
    return _review_engine


def get_template_store() -> TemplateStore:
    """FastAPI dependency: return the shared TemplateStore."""
    from autogen.llm.prompts.templates import TemplateStore

    assert _template_store is not None, "TemplateStore not initialised"
    return _template_store


def get_explorer_engine() -> ExplorerEngine:
    """FastAPI dependency: return the shared ExplorerEngine."""
    from autogen.explorer.engine import ExplorerEngine

    assert _explorer_engine is not None, "ExplorerEngine not initialised"
    return _explorer_engine
