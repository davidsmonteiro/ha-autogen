# CLAUDE.md — HA AutoGen

## Project Overview

HA AutoGen is a Home Assistant add-on that generates automations and Lovelace dashboards from natural language requests, and reviews existing configurations for improvements. It runs as a Docker container within the HA Supervisor ecosystem, serving a web UI through HA's ingress proxy.

The PRD is at `docs/HA_AutoGen_PRD.docx` — read it for full context on requirements, architecture, and phasing.

## Architecture

```
ha-autogen/                          # Repository root
├── CLAUDE.md
├── README.md
├── repository.yaml                  # HA add-on repository manifest
├── docs/
│   └── HA_AutoGen_PRD.docx
├── ha_autogen/                      # Add-on directory (HA Supervisor reads this)
│   ├── config.yaml                  # HA add-on manifest
│   ├── Dockerfile                   # Alpine-based Python image
│   ├── run.sh                       # Add-on entrypoint
│   ├── requirements.txt
│   ├── autogen/                     # Python package
│   │   ├── __init__.py
│   │   ├── main.py                  # FastAPI app, ingress entrypoint
│   │   ├── context/                 # Context Engine
│   │   ├── llm/                     # LLM Interface + prompts
│   │   ├── validator/               # Validation Pipeline
│   │   ├── reviewer/                # Configuration Review Engine
│   │   ├── deployer/                # Deploy & Rollback
│   │   ├── explorer/                # Automation opportunity analysis
│   │   ├── db/                      # SQLite persistence
│   │   └── api/                     # FastAPI routes
│   └── frontend/
│       └── index.html               # Single-page htmx UI
└── tests/
    ├── conftest.py
    ├── fixtures/                    # Sample HA entity/automation data
    ├── test_context/
    ├── test_llm/
    ├── test_validator/
    ├── test_reviewer/
    ├── test_deployer/
    ├── test_explorer/
    └── test_templates/
```

## Tech Stack

- **Runtime:** Python 3.12+ on Alpine Linux (Docker)
- **Web framework:** FastAPI with uvicorn
- **HA communication:** WebSocket API (aiohttp) for registry pulls, REST API (httpx) for CRUD
- **YAML:** ruamel.yaml (round-trip parsing, comment preservation)
- **LLM client:** httpx (async, no heavy SDK deps)
- **Validation:** voluptuous (HA's own schema lib) + custom checkers
- **Database:** SQLite via aiosqlite (stored in /data/ for persistence)
- **Frontend editor:** CodeMirror 6 (YAML mode, diff view)

## Key Design Decisions

### HA Add-on Architecture
- The add-on gets a Supervisor API token automatically via `$SUPERVISOR_TOKEN`
- All HA API calls go through `http://supervisor/core/api/` (internal Supervisor network)
- The web UI is served on the ingress port; HA proxies it with user auth
- Persistent data lives in `/data/` (survives add-on updates); config dir mapped for YAML writes

### LLM Backend Abstraction
All backends implement the same interface (`llm/base.py`). The key method is:
```python
async def generate(self, system_prompt: str, user_prompt: str, context: dict) -> LLMResponse
```
Streaming is optional per backend. Response parsing (extracting YAML from code fences) is shared.

### Context Engine Token Budget
Large HA instances can have 1000+ entities. The context engine must:
1. Pull all registries once and cache (refresh on demand or via WS subscription)
2. For each request, filter entities by relevance (keyword matching on the user's request against entity names, areas, domains)
3. Fit within the model's context window, reserving space for system prompt + output
4. Include full details for relevant entities, summaries for others

### Validation-First Approach
Never present unvalidated YAML to the user. The pipeline runs automatically:
1. YAML syntax → 2. Entity refs → 3. Service calls → 4. Schema → 5. Duplicates
If steps 1 or 4 fail, retry with the LLM (include error in retry prompt, max 2 retries). Steps 2/3/5 produce warnings, not blocks.

### Review Engine
The reviewer uses the LLM but with a different prompt strategy — it sends existing automation/dashboard YAML plus the entity context, and asks for structured analysis output. Findings are parsed into typed models (severity, description, affected item, suggested fix YAML). The fix YAML feeds directly into the standard validation → review → deploy pipeline.

## Home Assistant API Patterns

### WebSocket API (registry pulls)
```python
# Connect via aiohttp
async with aiohttp.ClientSession() as session:
    async with session.ws_connect(
        "ws://supervisor/core/websocket",
        headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}"}
    ) as ws:
        # Auth
        await ws.send_json({"type": "auth", "access_token": SUPERVISOR_TOKEN})
        # Request entity registry
        await ws.send_json({"id": 1, "type": "config/entity_registry/list"})
        # Request area registry
        await ws.send_json({"id": 2, "type": "config/area_registry/list"})
```

### REST API (deploy)
```python
# Reload automations after writing YAML
await httpx_client.post(
    "http://supervisor/core/api/services/automation/reload",
    headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}"}
)
```

### Lovelace Storage API
```python
# Get current dashboard config
resp = await httpx_client.get(
    "http://supervisor/core/api/lovelace/config",
    headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}"}
)
# Save updated dashboard
await httpx_client.post(
    "http://supervisor/core/api/lovelace/config",
    headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}"},
    json=new_config
)
```

## Add-on Manifest (config.yaml)

```yaml
name: "HA AutoGen"
description: "Natural language automation & dashboard generator with config review"
version: "0.1.0"
slug: "ha_autogen"
url: "https://github.com/YOUR_REPO/ha-autogen"
arch:
  - aarch64
  - amd64
homeassistant_api: true
ingress: true
ingress_port: 8099
auth_api: true
panel_icon: "mdi:robot"
panel_title: "AutoGen"
map:
  - config:rw
options:
  llm_backend: "ollama"
  llm_api_url: "http://homeassistant.local:11434"
  llm_api_key: ""
  llm_model: ""
  auto_backup: true
  max_context_entities: 200
schema:
  llm_backend: list(ollama|anthropic|openai_compat)
  llm_api_url: url
  llm_api_key: password
  llm_model: str?
  auto_backup: bool
  max_context_entities: int(50,500)
```

## Development Workflow

### Local Development (without HA)
For development and testing without a live HA instance, the context engine should support a mock mode that loads fixture data from `tests/fixtures/`. This allows rapid iteration on the LLM prompts, validation pipeline, and UI without needing a real HA setup.

```bash
# Run in dev mode with mock HA data
AUTOGEN_DEV_MODE=true uvicorn autogen.main:app --reload --port 8099
```

### Testing
- Use pytest with pytest-asyncio for async tests
- Mock the HA WebSocket/REST APIs using fixtures
- LLM responses should be mockable for deterministic validation tests
- Include golden-file tests: known input requests → expected YAML output structure (not exact content, but schema compliance)

### Building the Add-on
```bash
docker build -t ha-autogen .
# Or for local HA testing, copy to the addons directory:
# cp -r . /path/to/ha/addons/ha-autogen/
```

## Prompt Engineering Notes

### System Prompt Structure
The system prompt should be modular and assembled at request time:
1. **Role definition** — "You are HA AutoGen, an expert Home Assistant YAML generator..."
2. **Output rules** — YAML in code fences, inline comments, schema compliance
3. **HA conventions** — Automation structure, trigger platforms, service call format, Lovelace card types
4. **Entity context** — Injected by the context engine, filtered by relevance
5. **Request-type-specific instructions** — Different for generation vs. review vs. modification

### Critical Prompt Rules
- Always instruct the LLM to ONLY use entity IDs from the provided context
- For review prompts, require structured output (JSON with severity, description, fix fields)
- Include 1-2 few-shot examples in the system prompt for the output format
- For modification requests, include the existing YAML and instruct "modify this, don't rewrite from scratch"

## Coding Conventions

- Python 3.12+, type hints everywhere, async/await for all I/O
- Pydantic v2 models for all data structures (API request/response, LLM response parsing, review findings)
- FastAPI dependency injection for shared resources (HA client, LLM backend, DB session)
- Use `logging` with structured output (JSON logs for production, human-readable for dev)
- ruamel.yaml for all YAML operations (never PyYAML — it drops comments)
- Error handling: never surface raw LLM output or tracebacks to the user; always wrap in user-friendly messages

## Security Considerations

- API keys stored server-side only, never exposed to frontend JS
- Flag automations touching sensitive domains: `lock`, `alarm_control_panel`, `cover`, `camera`, `siren` — add a confirmation step with explicit warning text
- The deployer must always backup before writing, no exceptions
- Validate all user input (natural language requests) before passing to the LLM — sanitise to prevent prompt injection via entity names or automation descriptions
- Rate-limit LLM calls to prevent accidental cost spikes (configurable, default: 30 requests/hour)

## Phase 1 Priorities (Start Here)

1. **Add-on scaffold** — Dockerfile, config.yaml, run.sh, FastAPI app serving through ingress
2. **Context Engine** — Entity, area, device registry pulls via WebSocket. Start with `context/engine.py` orchestrating `entities.py` and `areas.py`
3. **LLM Interface** — Ollama backend first (`llm/ollama.py`), basic prompt template (`llm/prompts/system.py` + `automation.py`)
4. **Minimal API** — `POST /api/generate` that wires context → prompt → LLM → raw response
5. **Minimal UI** — Single page: text input, submit button, YAML output display (no editor yet)
6. **Dev mode** — Mock HA data from fixtures for testing without a live instance
