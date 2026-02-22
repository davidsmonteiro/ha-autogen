# HA AutoGen

A Home Assistant add-on that generates automations and Lovelace dashboards from natural language, reviews existing configurations for improvements, and suggests new automations based on your setup.

## Features

- **Generate automations** — Describe what you want in plain English and get valid HA YAML
- **Generate dashboards** — Request Lovelace views by describing rooms, devices, or layouts
- **Review configurations** — Analyze existing automations and dashboards for issues, best practices, and improvements
- **Explore opportunities** — Discover untapped automation potential based on your entity inventory
- **Validate before deploy** — YAML syntax, entity references, service calls, and schema are all checked automatically
- **Deploy with backup** — One-click deploy with automatic rollback support
- **Prompt templates** — Customize generation and review behavior with user-defined prompt additions

## Supported LLM Backends

| Backend | Config value | Notes |
|---------|-------------|-------|
| Ollama (local) | `ollama` | Default. Runs on your own hardware, no API key needed |
| OpenAI-compatible | `openai_compat` | Works with LM Studio, text-generation-webui, vLLM, etc. |
| Anthropic Claude | `anthropic` | Requires API key |

## Installation

### As a Home Assistant Add-on

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**
2. Click the three-dot menu → **Repositories** and add this repository URL
3. Find **HA AutoGen** in the list and click **Install**
4. Configure your LLM backend in the add-on **Configuration** tab:
   - **llm_backend**: `ollama`, `openai_compat`, or `anthropic`
   - **llm_api_url**: URL of your LLM API (e.g., `http://homeassistant.local:11434` for Ollama)
   - **llm_api_key**: API key (only needed for Anthropic / keyed endpoints)
   - **llm_model**: Model name (leave blank for backend default)
5. Click **Start**, then open the **Web UI** via the sidebar panel or the add-on page

### Local Development (without HA)

Run with mock Home Assistant data for development and testing:

```powershell
# Clone and set up
git clone https://github.com/davidsmonteiro/ha-autogen.git
cd ha-autogen

# Create virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1   # Windows PowerShell
# source .venv/bin/activate  # Linux/macOS

# Install dependencies
pip install -r ha_autogen/requirements.txt

# Start dev server with mock HA data
$env:AUTOGEN_DEV_MODE="true"
$env:PYTHONPATH="ha_autogen"
uvicorn autogen.main:app --reload --port 8099
```

Open [http://localhost:8099](http://localhost:8099) in your browser.

Dev mode loads fixture data from `tests/fixtures/` so you can work on prompts, validation, and UI without a live HA instance. You still need a running LLM backend (e.g., Ollama) for generation and review features.

## Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `llm_backend` | `ollama` \| `anthropic` \| `openai_compat` | `ollama` | Which LLM backend to use |
| `llm_api_url` | URL | `http://homeassistant.local:11434` | LLM API endpoint |
| `llm_api_key` | string | *(empty)* | API key for authenticated backends |
| `llm_model` | string | *(empty)* | Model name (backend-specific default if blank) |
| `auto_backup` | bool | `true` | Backup configs before deploying |
| `max_context_entities` | int (50–500) | `200` | Max entities sent to LLM context |

## Architecture

```
autogen/
├── api/            # FastAPI route handlers
├── context/        # HA registry pulls, entity context, token budget
├── db/             # SQLite persistence, migrations
├── deployer/       # Config deployment, backup, rollback
├── explorer/       # Automation opportunity analysis
├── llm/            # LLM backend abstraction + prompt templates
├── reviewer/       # Configuration review engine (rules + LLM)
└── validator/      # YAML, entity ref, service call, schema validation
frontend/
└── index.html      # Single-page htmx UI (5 tabs)
tests/
├── fixtures/       # Mock HA registry data
└── test_*/         # pytest suites (181 tests)
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/generate` | Generate automation or dashboard YAML |
| `POST` | `/api/review` | Review existing configurations |
| `POST` | `/api/explore` | Discover automation opportunities |
| `POST` | `/api/deploy` | Deploy generated YAML to HA |
| `POST` | `/api/rollback/{id}` | Roll back a deployment |
| `GET` | `/api/history` | List generation/deploy history |
| `GET` | `/api/history/{id}` | Get a single history entry |
| `GET/POST/PUT/DELETE` | `/api/templates` | Manage prompt templates |
| `GET` | `/api/context/areas` | List HA areas |
| `GET` | `/api/context/automations` | List existing automations |
| `GET` | `/api/context/views` | List dashboard views |
| `GET` | `/api/health` | Health check |

## Running Tests

```powershell
.venv\Scripts\Activate.ps1
pytest tests/ -v
```

No live HA instance or LLM backend is required — all external calls are mocked.

## Tech Stack

- **Python 3.12+** / FastAPI / uvicorn
- **ruamel.yaml** for round-trip YAML parsing
- **SQLite** (aiosqlite) for history and templates
- **htmx** + CodeMirror 6 for the frontend
- Runs as an Alpine Linux Docker container in the HA Supervisor ecosystem

## License

MIT
