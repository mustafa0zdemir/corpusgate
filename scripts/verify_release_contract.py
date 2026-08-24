from __future__ import annotations

import re
import tomllib
from pathlib import Path

from app import __version__
from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["name"] == "corpusgate"
    assert pyproject["project"]["dynamic"] == ["version"]
    assert pyproject["tool"]["hatch"]["version"]["path"] == "app/_version.py"
    assert set(pyproject["project"]["scripts"]) == {
        "corpusgate",
        "corpusgate-mcp",
        "corpusgate-backup",
        "corpusgate-reindex-cache",
        "corpusgate-semantic",
        "corpusgate-evaluate",
        "corpusgate-admin",
    }
    assert __version__ == "0.1.0"
    assert f"## [{__version__}]" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert f"ARG CORPUSGATE_VERSION={__version__}" in dockerfile
    assert "USER 10001:10001" in dockerfile

    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    documented = set(
        re.findall(r"^(?:# )?CORPUSGATE_([A-Z0-9_]+)=", env_example, flags=re.MULTILINE)
    )
    missing = {
        name.upper()
        for name in Settings.model_fields
        if name != "app_name" and name.upper() not in documented
    }
    assert not missing, f"Settings missing from .env.example: {sorted(missing)}"

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("# CorpusGate\n")
    assert "./corpusgate init" in readme
    assert (ROOT / "corpusgate").is_file()

    required_files = (
        "README.md",
        "LICENSE",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CODE_OF_CONDUCT.md",
        "SUPPORT.md",
        "docs/configuration.md",
        "docs/container-publishing.md",
        "docs/demo.md",
        "docs/mcp-connection.md",
        "docs/release-checklist.md",
    )
    assert all((ROOT / name).is_file() for name in required_files)
    print(f"release contract verified for {__version__}")


if __name__ == "__main__":
    main()
