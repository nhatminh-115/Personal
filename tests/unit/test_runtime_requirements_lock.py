"""Keep generated requirements files aligned with direct project dependencies."""

import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


ROOT = Path(__file__).resolve().parents[2]


def _locked_requirements(path: Path) -> dict[str, Requirement]:
    requirements: dict[str, Requirement] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#") or line[:1].isspace():
            continue
        requirement = Requirement(candidate)
        requirements[canonicalize_name(requirement.name)] = requirement
    return requirements


def test_runtime_and_dev_locks_cover_direct_project_dependencies():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    direct = {
        canonicalize_name(Requirement(value).name): Requirement(value)
        for value in project["project"]["dependencies"]
    }
    runtime = _locked_requirements(ROOT / "requirements.lock")
    development = _locked_requirements(ROOT / "requirements-dev.lock")

    assert not (missing := sorted(direct.keys() - runtime.keys())), (
        f"requirements.lock is missing: {missing}"
    )
    assert not (missing := sorted(direct.keys() - development.keys())), (
        f"requirements-dev.lock is missing: {missing}"
    )

    sqlalchemy = direct.get("sqlalchemy")
    if sqlalchemy and "asyncio" in sqlalchemy.extras:
        assert "greenlet" in runtime, "SQLAlchemy's asyncio extra requires greenlet in requirements.lock"
