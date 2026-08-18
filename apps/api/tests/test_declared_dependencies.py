"""Every service must start from the declared requirements alone.

Two dependencies were reaching the environment only as transitive dependencies
of `agent-reach`, so the requirements files never actually described what the
code needs. Moving that package to an optional extra surfaced both at once:

* `feedparser`, imported directly by the RSS and search adapters.
* `python-multipart`, which FastAPI needs to accept the `Form()` data the dev
  OIDC issuer serves. Nothing imports it by name, so it is invisible to both
  mypy and a plain import check of the module list -- it only fails when the
  app object is constructed and the routes are registered.

Importing each service entrypoint constructs its FastAPI app, which is what
makes the second case detectable at all.
"""

from __future__ import annotations

import importlib

import pytest


SERVICE_ENTRYPOINTS = [
    "apps.api.app.main",
    "services.research_gateway.app.main",
    "services.worker.app.main",
    "services.dev_oidc.main",
]


@pytest.mark.parametrize("module", SERVICE_ENTRYPOINTS)
def test_service_entrypoint_imports(module: str) -> None:
    """A missing runtime dependency fails here rather than in production."""
    importlib.import_module(module)


def test_every_third_party_import_is_declared() -> None:
    """Catch the next undeclared direct import before it reaches a runner.

    Only covers `import x` / `from x import ...` at the top level of the
    application packages; a dependency used purely through a framework hook
    (python-multipart) still needs the import test above.
    """
    import pathlib
    import re
    import sys

    root = pathlib.Path(__file__).resolve().parents[3]
    declared_text = "\n".join(
        (root / "apps" / "api" / name).read_text(encoding="utf-8")
        for name in ("requirements.txt", "requirements-dev.txt")
    )
    declared = {
        match.group(1).lower().replace("_", "-")
        for match in re.finditer(r"^([A-Za-z0-9_.-]+)\s*[=@]", declared_text, re.MULTILINE)
    }
    # Local packages installed from source, e.g. `-e ./packages/entity-safety`.
    # The directory name is the distribution name; the module it provides is the
    # same with dashes as underscores.
    declared |= {
        match.group(1).lower()
        for match in re.finditer(
            r"^-e\s+\./packages/([A-Za-z0-9_-]+)", declared_text, re.MULTILINE
        )
    }
    # Distribution name differs from the module it installs.
    aliases = {"pyjwt": "jwt", "python-multipart": "multipart", "sqlalchemy": "sqlalchemy"}
    declared |= {module for module in aliases.values()}

    pattern = re.compile(r"^\s*(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.MULTILINE)
    offenders: set[str] = set()
    for package in ("apps/api/app", "services/research_gateway/app", "services/worker/app"):
        for path in (root / package).rglob("*.py"):
            for match in pattern.finditer(path.read_text(encoding="utf-8")):
                name = match.group(1)
                if name in sys.stdlib_module_names or name in {"apps", "services", "scripts"}:
                    continue
                if name.lower().replace("_", "-") in declared:
                    continue
                offenders.add(name)

    assert not offenders, (
        f"imported but not declared in requirements: {sorted(offenders)}. "
        "Add them, or they will work locally and fail on a clean machine."
    )
