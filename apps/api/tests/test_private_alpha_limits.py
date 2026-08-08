"""Invite-only access and bounded usage for the private alpha.

Two properties matter more than the individual numbers:

* every limit refuses with an explicit error rather than silently truncating, and
* the invite gate fails closed.

A caller who imports 300 accounts and silently receives 100 has been given a wrong
answer, not a partial one, so the tests assert the refusal rather than a cap.
"""

from __future__ import annotations

import pytest

from apps.api.app.config import Settings
from apps.api.app.services.private_alpha import (
    AccessDenied,
    LimitExceeded,
    assert_export_size,
    assert_import_size,
    assert_invited,
    experimental_discovery_allowed,
)


def _alpha(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "private_alpha_enabled": True,
        "private_alpha_allowed_subjects": ("invited-subject",),
        "private_alpha_allowed_emails": ("founder@example.com",),
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


# ------------------------------------------------------------------- invite gate


def test_invited_subject_is_admitted() -> None:
    assert_invited("invited-subject", None, _alpha())


def test_invited_email_is_admitted_case_insensitively() -> None:
    assert_invited("unknown-subject", "Founder@Example.COM", _alpha())


def test_uninvited_identity_is_refused() -> None:
    with pytest.raises(AccessDenied):
        assert_invited("stranger", "stranger@example.com", _alpha())


def test_gate_is_inactive_when_the_private_alpha_is_off() -> None:
    assert_invited("anyone", None, Settings(private_alpha_enabled=False))


def test_an_empty_invite_list_is_rejected_at_startup() -> None:
    """Admitting no one is far more likely a misconfiguration than an intent."""
    with pytest.raises(RuntimeError, match="PRIVATE_ALPHA_ALLOWED"):
        Settings(
            private_alpha_enabled=True,
            private_alpha_allowed_subjects=(),
            private_alpha_allowed_emails=(),
        ).validate()


# --------------------------------------------------------- experimental discovery


def test_discovery_is_off_by_default_during_the_private_alpha() -> None:
    assert experimental_discovery_allowed(_alpha()) is False


def test_discovery_can_be_switched_on_explicitly() -> None:
    assert experimental_discovery_allowed(
        _alpha(allow_experimental_discovery=True)
    ) is True


def test_discovery_is_unrestricted_outside_the_private_alpha() -> None:
    assert experimental_discovery_allowed(Settings(private_alpha_enabled=False)) is True


# -------------------------------------------------------------------- size limits


def test_oversized_import_is_refused_rather_than_truncated() -> None:
    config = _alpha(max_accounts_per_import=100)

    with pytest.raises(LimitExceeded) as excinfo:
        assert_import_size(300, config)

    error = excinfo.value
    assert error.code == "IMPORT_TOO_LARGE"
    assert error.limit == 100
    assert error.attempted == 300
    assert "Nothing was imported" in error.message


def test_import_at_exactly_the_limit_is_allowed() -> None:
    assert_import_size(100, _alpha(max_accounts_per_import=100))


def test_oversized_export_is_refused_rather_than_truncated() -> None:
    with pytest.raises(LimitExceeded) as excinfo:
        assert_export_size(5000, _alpha(max_export_rows=1000))

    assert excinfo.value.code == "EXPORT_TOO_LARGE"
    assert "misleading" in excinfo.value.message


def test_export_at_exactly_the_limit_is_allowed() -> None:
    assert_export_size(1000, _alpha(max_export_rows=1000))


def test_limit_detail_is_machine_readable_and_leaks_nothing() -> None:
    error = LimitExceeded(
        code="IMPORT_TOO_LARGE", message="too many", limit=100, attempted=300
    )

    detail = error.as_detail()

    assert detail == {
        "code": "IMPORT_TOO_LARGE",
        "message": "too many",
        "limit": 100,
        "attempted": 300,
    }


@pytest.mark.parametrize(
    "field",
    [
        "max_accounts_per_import",
        "max_accounts_per_workspace",
        "max_imports_per_day",
        "max_concurrent_research_runs",
        "max_workspaces_per_user",
        "max_export_rows",
        "max_pages_per_account",
    ],
)
def test_non_positive_limits_are_rejected_at_startup(field: str) -> None:
    with pytest.raises(RuntimeError, match=field.upper()):
        Settings(**{field: 0}).validate()  # type: ignore[arg-type]
