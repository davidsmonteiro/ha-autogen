# Changelog

## 0.2.1

- **Multi-dashboard deploy**: Dashboard deploy no longer overwrites the default dashboard — users choose to create a new dashboard, deploy to an existing one, or explicitly target the default
- New `GET /api/dashboards` endpoint lists all available Lovelace dashboards
- Dashboard selector dialog with "Create New Dashboard" as the safe default
- Support for HA WebSocket API: `lovelace/dashboards/list`, `lovelace/dashboards/create`, `lovelace/config` with `url_path`

## 0.2.0

- **Plan Mode**: Iterative plan-then-generate flow — LLM proposes a structured plan (entities, triggers, conditions, actions, assumptions, questions) that you review, edit, and refine before YAML generation
- **Quick Fixes**: Review findings classified as Quick Fix (one-click apply) or Guided Fix (enters Plan Mode), with batch "Fix All" and sensitive domain confirmation
- **Entity search**: Add entities to plans via search with autocomplete from your HA instance
- **Refinement autocomplete**: Entity ID autocomplete in refinement notes (arrow keys + Tab)
- **DB migration v4**: New plans and fix_applications tables
- Fix: status message elements changed from span to div (PR #4)

## 0.1.0

- Initial release
- Context engine with entity, area, device, service, automation, and dashboard registry pulls
- LLM backends: Ollama, OpenAI-compatible
- Automation and dashboard generation from natural language
- Validation pipeline (YAML syntax, entity refs, service calls, schema, duplicates)
- Configuration review with deterministic rules + LLM analysis
- Deploy and rollback with automatic backups
- Explore mode with automation suggestions
- Prompt template customization
- Entity autocomplete in YAML editor
- Dev mode with mock HA data
