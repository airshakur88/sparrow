# PROJECT KNOWLEDGE BASE

**Generated:** 2026-09-16
**Commit:** 0.0.0
**Branch:** main

## OVERVIEW
Sparrow is a free LLM gateway providing 18 providers, 152 chat routes, and 152 cataloged models with keyless start when available. Built as a Python package with CLI, HTTP proxy, and programmatic API.

## STRUCTURE
```
sparrow/
├── src/sparrow/      # Core package (50+ modules)
├── tests/            # 63 test files
├── scripts/          # 6 utility scripts
├── .github/workflows/# 5 CI/CD workflows
├── .codegraph/       # Codegraph metadata & database
├── .omo/             # Session continuation files
├── dist/             # Built artifacts
├── pyproject.toml    # Hatchling build config
├── Dockerfile        # Alpine-based container
├── docker-compose.yml# Compose with open-webui
└── config.md         # Configuration template
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| CLI entry point | src/sparrow/cli.py:main() | 14 subcommands |
| HTTP proxy server | src/sparrow/proxy.py:serve() | 3095 lines |
| Core routing logic | src/sparrow/router.py:Pool | 1904 lines |
| Configuration | src/sparrow/config.py | load_catalog, settings |
| Credential management | src/sparrow/credential_*.py | Store, manager, CLI |
| Provider catalog | src/sparrow/providers.toml | 18 providers, 152 models |
| Capability scoring | src/sparrow/capability_scores.json | Model capability data |
| Test fixtures | tests/fixtures/ | grounded_reading.json |
| CI pipeline | .github/workflows/ci.yml | Test, lint, docker, release |

## CODE MAP
| Symbol | Type | Location | Refs | Role |
|--------|------|----------|------|------|
| main | function | src/sparrow/cli.py:1240 | 1 | CLI entry point |
| Pool | class | src/sparrow/router.py:1 | 12 | Core orchestrator |
| serve | function | src/sparrow/proxy.py:3025 | 2 | HTTP server |
| load_catalog | function | src/sparrow/config.py:540 | 8 | Provider catalog |
| configured_providers | function | src/sparrow/config.py:564 | 6 | Filter configured |
| CredentialStore | class | src/sparrow/credential_store.py:32 | 5 | Credential persistence |
| KeyInventory | class | src/sparrow/key_inventory.py:1 | 3 | Key management |
| ConformanceStore | class | src/sparrow/conformance.py:1 | 4 | Conformance checking |
| call | function | src/sparrow/client.py:152 | 15 | HTTP client |
| run_panel | function | src/sparrow/panel.py:1 | 2 | Second-opinion panel |

## CONVENTIONS
- Python ≥3.11, strict mypy, ruff line-length=100
- Hatchling build with force-include for data files
- All providers in providers.toml (packaged data)
- Lazy AsyncPool import via __getattr__ in __init__.py
- Private members prefixed with _ (but aio.py imports them)
- Excessive whitespace in source files (non-standard)

## ANTI-PATTERNS (THIS PROJECT)
- DO NOT use excessive whitespace/blank lines in source files
- DO NOT import private members from router.py (aio.py violates this)
- DO NOT use --allow-no-auth in production Docker CMD
- DO NOT use "anything" as default API key in docker-compose
- DO NOT leave recipes/ directory empty
- DO NOT pin certifi to date-based version (2026.7.22)
- DO NOT hardcode version="0.0.0" in pyproject.toml
- DO NOT use urllib for healthchecks (use curl)
- DO NOT define all cmd_* functions at module level in cli.py

## UNIQUE STYLES
- Providers defined in TOML, loaded at runtime
- Capability scores as JSON data file
- Task quality routing via regex classification
- Second-opinion panel with synthesis
- Tailnet integration for secure LAN access
- SVG badge generation for usage stats

## COMMANDS
```bash
# Development
pip install -e ".[dev]"
ruff check .
pytest --cov=sparrow --cov-branch
mypy --follow-imports=skip src/sparrow/routing_modes.py src/sparrow/catalog_validation.py src/sparrow/_version.py src/sparrow/readiness.py
python scripts/validate_catalog.py
python scripts/check_release_ready.py --skip-build
python scripts/stress_proxy.py --profile ci

# Build
python -m build
twine check dist/*

# Run
sparrow ask "prompt"
sparrow start --host 0.0.0.0 --port 8080
sparrow providers health
sparrow models --json
```

## NOTES
- Version 0.0.0 conflicts with release validation gates
- YAML indentation errors in docker.yml:42 and release-evidence.yml:51
- 240+ session files in .omo/run-continuation/
- proxy.py (3095 lines) and router.py (1904 lines) need decomposition
- aio.py imports private members from router.py
- benchmark.py uses _client module alias
- docker-compose.yml has 25+ API key env vars
