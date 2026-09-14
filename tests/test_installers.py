from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GITHUB_SOURCE = "git+https://github.com/airshakur88/sparrow@"


def test_shell_installer_uses_github_source_and_current_tool_path():
    content = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert GITHUB_SOURCE in content
    assert "tool install --python 3.11 --force sparrow\n" not in content
    assert "tool dir --bin" in content
    assert "command -v sparrow" in content
    assert "sparrow --version" in content


def test_powershell_installer_uses_github_source_and_current_tool_path():
    content = (ROOT / "install.ps1").read_text(encoding="utf-8")

    assert GITHUB_SOURCE in content
    assert "tool install --python 3.11 --force sparrow\n" not in content
    assert "tool dir --bin" in content
    assert "Get-Command sparrow" in content
    assert "sparrow --version" in content
