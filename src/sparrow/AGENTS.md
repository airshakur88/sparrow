# SPARROW CORE PACKAGE

**Generated:** 2026-09-16
**Score:** 28 (high complexity)

## OVERVIEW
Core package with 50+ modules implementing LLM gateway: routing, credentials, proxy, conformance, and provider adapters.

## STRUCTURE
```
src/sparrow/
├── cli.py              # 1260 lines - 14 subcommands
├── proxy.py            # 3095 lines - HTTP server
├── router.py           # 1904 lines - Pool orchestrator
├── config.py           # 571 lines - Catalog, settings
├── client.py           # 1005 lines - HTTP adapters
├── conformance.py      # 654 lines - Canary/feature checks
├── credential_*.py     # 7 modules - Key management
├── aio.py              # AsyncPool (lazy import)
├── panel.py            # Second-opinion panel
├── mode.py             # Routing modes
├── tailnet.py          # Tailnet integration
├── quota.py            # Quota tracking
├── stats.py            # Usage persistence
├── cache.py            # Response caching
├── recipes/            # EMPTY - remove or populate
├── providers.toml      # 18 providers, 157 models
├── capability_scores.json
├── task_evidence.json
└── __init__.py         # Lazy AsyncPool via __getattr__
```

## WHERE TO LOOK
| Task | Location |
|------|----------|
| CLI commands | cli.py:cmd_* functions |
| HTTP server | proxy.py:serve(), make_handler() |
| Routing logic | router.py:Pool class |
| Provider config | config.py:load_catalog() |
| Credentials | credential_store.py, credential_manager.py |
| Conformance | conformance.py:ConformanceStore |
| Async API | aio.py:AsyncPool |

## CONVENTIONS
- Private members prefixed with _ (but aio.py violates this)
- Excessive whitespace in all files (non-standard)
- Data files (TOML/JSON) packaged via hatch force-include
- Task quality routing via regex in task_quality.py

## ANTI-PATTERNS
- DO NOT import private members from router.py (aio.py does this)
- DO NOT leave recipes/ empty
- DO NOT use excessive whitespace/blank lines
- DO NOT define all cmd_* at module level in cli.py
- DO NOT use _client alias in benchmark.py
- DO NOT hardcode version="0.0.0"