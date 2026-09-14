                                                

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sparrow_package_is_importable():
    import sparrow

    assert sparrow.__version__


def test_root_publishes_only_the_sparrow_console_script():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["scripts"] == {"sparrow": "sparrow.cli:main"}

