# CI/CD WORKFLOWS

**Generated:** 2026-09-16
**Score:** 15 (distinct domain)

## OVERVIEW
5 GitHub Actions workflows for CI, Docker, security, CodeQL, and release evidence.

## STRUCTURE
```
.github/workflows/
├── ci.yml              # Main CI: test, lint, validate, docker-smoke
├── docker.yml          # Docker build, scan, publish (reusable)
├── release-evidence.yml# Release artifact collection
├── security.yml        # Scheduled security scans
└── codeql.yml          # CodeQL analysis
```

## WHERE TO LOOK
| Task | Location |
|------|----------|
| Full CI pipeline | ci.yml |
| Docker build/publish | docker.yml (workflow_call) |
| Release artifacts | release-evidence.yml |
| Security scans | security.yml (Tue 4:47 AM) |
| CodeQL analysis | codeql.yml (Tue 4:31 AM) |

## CONVENTIONS
- All actions pinned to commit SHAs (supply-chain security)
- Python matrix: 3.11, 3.12, 3.13, 3.14
- Coverage gates: 80% lines, 70% branches
- Docker smoke test on built image

## ANTI-PATTERNS
- DO NOT use leading whitespace in run: blocks (docker.yml:42, release-evidence.yml:51)
- DO NOT hardcode version="0.0.0" (conflicts with release gate)
- DO NOT use --allow-no-auth in Docker CMD
- DO NOT use "anything" as default API key in docker-compose
- DO NOT use urllib for healthchecks (use curl)