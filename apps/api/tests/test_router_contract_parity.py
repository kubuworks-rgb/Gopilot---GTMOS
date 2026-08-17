"""The two routers must not drift apart silently.

`main.py` selects `routes.py` (fixture) or `live_routes.py` (live) at import time.
They implement the same product against different repositories, so a contract
change has to be made twice -- and one already had been missed: the export column
lists diverged until they were consolidated into `services/exports.py`.

Merging the routers outright is a real refactor, because the fixture repository is
synchronous and session-less while the Postgres one is async with session
injection. Until that happens, this guards the boundary: every shared path must
agree on its methods, and any endpoint that exists only in live mode must be
declared here deliberately rather than appearing by accident.
"""

from __future__ import annotations

import pytest

from apps.api.app.api import dependencies, live_routes, routes


# Endpoints that legitimately exist only in live mode: each needs a worker, a real
# research run, or persistence that the in-memory fixture repository has no
# equivalent for.
LIVE_ONLY = {
    # Queue a discovery run; needs the worker.
    "/accounts/refresh",
    # Queue per-account work; needs the worker.
    "/accounts/{account_id}/regenerate-brief",
    "/accounts/{account_id}/research",
    # Records QA evaluations against a persisted run and account.
    "/qa-evaluations",
    # Returns source documents, chunks and evidence facts for a run. The fixture
    # repository holds no chunk-level data to serve.
    "/research-runs/{run_id}/evidence",
}


def _paths(router) -> dict[str, set[str]]:  # type: ignore[no-untyped-def]
    found: dict[str, set[str]] = {}
    for route in router.router.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        found.setdefault(path, set()).update(methods - {"HEAD", "OPTIONS"})
    return found


FIXTURE = _paths(routes)
LIVE = _paths(live_routes)
SHARED = sorted(set(FIXTURE) & set(LIVE))


def test_the_fixture_router_exposes_no_endpoint_live_mode_lacks() -> None:
    """Live is the real product; fixture must never be ahead of it."""
    fixture_only = set(FIXTURE) - set(LIVE)

    assert fixture_only == set(), (
        f"fixture-only endpoints would be unreachable in production: {fixture_only}"
    )


def test_live_only_endpoints_are_declared_deliberately() -> None:
    prefix = live_routes.router.prefix
    live_only = {
        path.removeprefix(prefix) for path in set(LIVE) - set(FIXTURE)
    }

    assert live_only == LIVE_ONLY, (
        "live-only endpoints changed. Add it to LIVE_ONLY with a reason, or "
        f"implement it in the fixture router. Difference: {live_only ^ LIVE_ONLY}"
    )


@pytest.mark.parametrize("path", SHARED)
def test_shared_paths_agree_on_methods(path: str) -> None:
    assert FIXTURE[path] == LIVE[path], (
        f"{path} accepts {sorted(FIXTURE[path])} in fixture mode but "
        f"{sorted(LIVE[path])} in live mode"
    )


def test_the_shared_surface_is_not_empty() -> None:
    """Guards against the comparison silently matching nothing."""
    assert len(SHARED) >= 15


def test_both_routers_use_the_same_prefix() -> None:
    assert routes.router.prefix == live_routes.router.prefix


@pytest.mark.asyncio
@pytest.mark.parametrize("resolver", ["fixture", "live"])
async def test_both_routers_enforce_the_invite_gate(
    monkeypatch: pytest.MonkeyPatch, resolver: str
) -> None:
    """The drift that actually bit twice: a gate added to one router only.

    `assert_invited` lived in `live_routes` alone, so in fixture mode any identity
    with a valid signature was admitted to an invite-only deployment. Authentication
    is not authorisation, and both routers have to ask both questions.
    """
    from fastapi import HTTPException

    from apps.api.app.config import Settings
    from apps.api.app.services import private_alpha

    alpha = Settings(
        private_alpha_enabled=True,
        auth_mode="demo",
        demo_auth_enabled=True,
        private_alpha_allowed_subjects=("invited",),
        private_alpha_allowed_emails=(),
    )
    # Settings is frozen, so replace the object each module resolved at import.
    for module in (dependencies, live_routes, private_alpha):
        monkeypatch.setattr(module, "settings", alpha)

    async def resolve(user: str) -> None:
        if resolver == "live":
            await live_routes.authenticated_user_id(None, user)
        else:
            await dependencies.get_principal(None, user, None)

    with pytest.raises(HTTPException) as refused:
        await resolve("stranger")
    assert refused.value.status_code == 403, (
        f"{resolver} router admitted an uninvited identity"
    )

    await resolve("invited")  # the gate must not refuse everyone


def test_export_is_defined_once_for_both() -> None:
    """The drift that actually bit: two copies of the export column list."""
    from apps.api.app.services.exports import EXPORT_COLUMNS

    assert routes.EXPORT_COLUMNS is EXPORT_COLUMNS
    assert live_routes.EXPORT_COLUMNS is EXPORT_COLUMNS
