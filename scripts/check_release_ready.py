#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def metadata_errors(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    server = json.loads((root / "server.json").read_text(encoding="utf-8"))
    version = project["version"]

    if project["name"] != "sparrow":
        errors.append("project name must be sparrow")
    if server.get("version") != version:
        errors.append("server.json version mismatch")
    if not (root / "src" / "sparrow" / "providers.toml").is_file():
        errors.append("packaged provider catalog is missing")
    if not (root / "src" / "sparrow" / "__init__.py").is_file():
        errors.append("sparrow package is missing")
    if "sparrow = \"sparrow.cli:main\"" not in (root / "pyproject.toml").read_text(
        encoding="utf-8"
    ):
        errors.append("sparrow console entry point is missing")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args(argv)
    errors = metadata_errors()
    if not errors and not args.skip_build:
        result = subprocess.run([sys.executable, "-m", "build"], cwd=ROOT, check=False)
        if result.returncode:
            errors.append("package build failed")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Release metadata ready for sparrow {tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
