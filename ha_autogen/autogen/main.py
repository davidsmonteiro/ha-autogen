"""FastAPI application -- HA AutoGen entrypoint."""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

import autogen.deps as deps
from autogen.api.context import router as context_router
from autogen.api.deploy import router as deploy_router
from autogen.api.generate import router as generate_router
from autogen.api.history import router as history_router
from autogen.api.review import router as review_router
from autogen.context.engine import ContextEngine
from autogen.db.database import Database
from autogen.llm.ollama import OllamaBackend
from autogen.llm.openai_compat import OpenAICompatBackend
from autogen.explorer.engine import ExplorerEngine
from autogen.llm.prompts.templates import TemplateStore
from autogen.reviewer.engine import ReviewEngine

logger = logging.getLogger(__name__)


def _load_options() -> dict:
    """Load add-on options from /data/options.json or env fallback."""
    opts_path = os.environ.get("AUTOGEN_OPTIONS_PATH", "/data/options.json")
    if Path(opts_path).exists():
        return json.loads(Path(opts_path).read_text())
    return {
        "llm_backend": os.environ.get("LLM_BACKEND", "ollama"),
        "llm_api_url": os.environ.get("LLM_API_URL", "http://localhost:11434"),
        "llm_api_key": os.environ.get("LLM_API_KEY", ""),
        "llm_model": os.environ.get("LLM_MODEL", "llama3.2"),
        "max_context_entities": int(os.environ.get("MAX_CONTEXT_ENTITIES", "200")),
    }


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: init resources on startup, clean up on shutdown."""
    log_level = logging.DEBUG if os.environ.get("AUTOGEN_DEV_MODE") else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    options = _load_options()
    logger.info(
        "HA AutoGen starting with options: %s",
        {k: v for k, v in options.items() if "key" not in k},
    )

    # Init database
    deps._database = Database()
    await deps._database.connect()
    logger.info("Database connected")

    # Init context engine
    deps._context_engine = ContextEngine()
    await deps._context_engine.refresh()

    # Init LLM backend
    backend_type = options.get("llm_backend", "ollama")
    api_url = options.get("llm_api_url", "http://localhost:11434")
    api_key = options.get("llm_api_key", "")
    model = options.get("llm_model", "llama3.2")

    if backend_type == "openai_compat":
        deps._llm_backend = OpenAICompatBackend(
            base_url=api_url,
            model=model,
            api_key=api_key,
        )
    else:
        deps._llm_backend = OllamaBackend(
            base_url=api_url,
            model=model,
        )
    logger.info("LLM backend: %s (model: %s)", backend_type, model)

    # Init review engine
    deps._review_engine = ReviewEngine(deps._llm_backend)

    # Init template store
    deps._template_store = TemplateStore(deps._database.conn)

    # Init explorer engine
    deps._explorer_engine = ExplorerEngine(deps._llm_backend)

    yield

    # Shutdown
    if hasattr(deps._llm_backend, "close"):
        await deps._llm_backend.close()
    if deps._database:
        await deps._database.close()
    deps._context_engine = None
    deps._llm_backend = None
    deps._database = None
    deps._review_engine = None
    deps._template_store = None
    deps._explorer_engine = None


app = FastAPI(
    title="HA AutoGen",
    version="0.1.0",
    lifespan=lifespan,
)

from autogen.api.explore import router as explore_router
from autogen.api.settings import router as settings_router

app.include_router(context_router)
app.include_router(explore_router)
app.include_router(generate_router)
app.include_router(deploy_router)
app.include_router(history_router)
app.include_router(review_router)
app.include_router(settings_router)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.get("/", response_class=HTMLResponse)
async def serve_frontend(request: Request) -> HTMLResponse:
    """Serve the single-page frontend."""
    index_path = FRONTEND_DIR / "index.html"
    html = index_path.read_text()
    ingress_path = request.headers.get("X-Ingress-Path", "")
    html = html.replace("__INGRESS_PATH__", ingress_path)
    return HTMLResponse(content=html)
