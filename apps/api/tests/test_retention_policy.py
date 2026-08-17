"""Retention must be stated, configurable, and never silently destructive.

Deleting a customer's research without asking is worse than keeping it too long, so
the window is a *policy* the product states and an operator applies, not a
background job. Automatic deletion is deliberately unimplemented and refuses to
start rather than being a flag someone can flip before the window is agreed.
"""

from __future__ import annotations

import pytest

from apps.api.app.config import Settings


def test_a_window_is_configured_by_default() -> None:
    assert Settings().research_retention_days > 0


def test_the_window_is_configurable() -> None:
    assert Settings(research_retention_days=30).research_retention_days == 30


@pytest.mark.parametrize("value", [0, -1])
def test_a_nonsensical_window_is_rejected_at_startup(value: int) -> None:
    with pytest.raises(RuntimeError, match="RESEARCH_RETENTION_DAYS"):
        Settings(research_retention_days=value).validate()


def test_automatic_deletion_is_off_by_default() -> None:
    assert Settings().retention_auto_delete is False


def test_enabling_automatic_deletion_refuses_to_start() -> None:
    """It is not implemented; failing loudly beats pretending it works."""
    with pytest.raises(RuntimeError, match="not implemented"):
        Settings(retention_auto_delete=True).validate()


def test_the_error_points_at_the_manual_path() -> None:
    with pytest.raises(RuntimeError) as excinfo:
        Settings(retention_auto_delete=True).validate()

    assert "apply_retention.py" in str(excinfo.value)


def test_a_default_configuration_still_validates() -> None:
    Settings().validate()
