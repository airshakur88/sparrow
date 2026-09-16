# TEST SUITE

**Generated:** 2026-09-16
**Score:** 18 (distinct domain)

## OVERVIEW
63 test files covering all core modules with pytest, fixtures, and helpers. Coverage gates: 80% lines, 70% branches.

## STRUCTURE
```
tests/
├── conftest.py              # Shared fixtures
├── helpers.py               # Test utilities
├── fixtures/                # Test data (grounded_reading.json)
├── test_*.py                # 63 test modules
└── __pycache__/
```

## WHERE TO LOOK
| Task | Location |
|------|----------|
| Fixtures | conftest.py, fixtures/ |
| CLI tests | test_cli.py |
| Router tests | test_router.py, test_routing.py |
| Credential tests | test_credential_*.py (12 files) |
| Proxy tests | test_proxy.py |
| Config tests | test_config.py, test_config_file.py |
| Conformance | test_conformance.py |

## CONVENTIONS
- pytest with -q flag
- pythonpath = [".", "src"]
- Coverage thresholds enforced via check_coverage.py
- Test names use descriptive patterns (test_*_never_*, test_*_always_*)

## ANTI-PATTERNS
- DO NOT use "never" or "always" in test names as anti-patterns (they're descriptive)
- DO NOT mock the SUT (system under test)
- DO NOT patch at definition site