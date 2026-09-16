# UTILITY SCRIPTS

**Generated:** 2026-09-16
**Score:** 12 (distinct domain)

## OVERVIEW
6 standalone utility scripts for CI/CD validation, coverage checking, release readiness, and proxy stress testing.

## STRUCTURE
```
scripts/
├── validate_catalog.py      # Validates providers.toml structure
├── check_release_ready.py   # Release metadata validation
├── check_coverage.py        # Enforces 80%/70% coverage gates
├── stress_proxy.py          # Proxy load testing
├── security_exceptions.py   # Security scan exceptions
└── __init__.py              # Makes scripts a package
```

## WHERE TO LOOK
| Task | Location |
|------|----------|
| Catalog validation | validate_catalog.py:main() |
| Release checks | check_release_ready.py:main() |
| Coverage gates | check_coverage.py:main() |
| Proxy stress | stress_proxy.py:main() |
| Security exceptions | security_exceptions.py:main() |

## CONVENTIONS
- Each script has its own main() function
- Not importable as part of sparrow package
- Used in CI pipeline (ci.yml)

## ANTI-PATTERNS
- DO NOT add business logic to scripts (keep in src/sparrow/)
- DO NOT make scripts depend on each other