"""Human review decisions must be stored (blueprint section 17).

A status change without the reasoning behind it is not much use to whoever opens
the account next, so notes and decisions are kept as an ordered history.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.api.app.domain.models import (
    AccountReviewEntry,
    AccountReviewStatus,
    AccountReviewUpdate,
    FeedbackInput,
)
from apps.api.app.repositories.postgres import _review_history


def test_a_review_can_carry_a_note() -> None:
    update = AccountReviewUpdate(
        review_status=AccountReviewStatus.CHANGES_REQUESTED,
        note="Size evidence is too weak to act on.",
    )

    assert update.note == "Size evidence is too weak to act on."


def test_a_review_without_a_note_is_still_valid() -> None:
    assert AccountReviewUpdate(review_status=AccountReviewStatus.APPROVED).note is None


def test_history_entries_round_trip() -> None:
    entry = AccountReviewEntry(
        actor_id="arun",
        review_status=AccountReviewStatus.APPROVED,
        brief_state="MONITOR",
        note="Good fit, waiting for a trigger.",
    )

    restored = AccountReviewEntry.model_validate(entry.model_dump(mode="json"))

    assert restored.actor_id == "arun"
    assert restored.note == "Good fit, waiting for a trigger."
    assert restored.recorded_at == entry.recorded_at


def test_history_is_read_back_in_order() -> None:
    attributes = {
        "review_history": [
            AccountReviewEntry(
                actor_id="arun",
                review_status=AccountReviewStatus.CHANGES_REQUESTED,
                note="first",
            ).model_dump(mode="json"),
            AccountReviewEntry(
                actor_id="arun",
                review_status=AccountReviewStatus.APPROVED,
                note="second",
            ).model_dump(mode="json"),
        ]
    }

    history = _review_history(attributes)

    assert [item.note for item in history] == ["first", "second"]


def test_a_malformed_history_entry_does_not_break_the_account() -> None:
    """One bad row must not make the whole account unreadable."""
    attributes = {
        "review_history": [
            {"nonsense": True},
            "not a dict",
            AccountReviewEntry(
                actor_id="arun", review_status=AccountReviewStatus.APPROVED
            ).model_dump(mode="json"),
        ]
    }

    history = _review_history(attributes)

    assert len(history) == 1
    assert history[0].actor_id == "arun"


@pytest.mark.parametrize("value", [None, "not a list", 42, {}])
def test_absent_or_wrong_shaped_history_reads_as_empty(value: object) -> None:
    assert _review_history({"review_history": value}) == []


# ----------------------------------------------------------------- corrections


def test_wrong_identity_is_its_own_correction() -> None:
    """Flagging the wrong company is distinct from a generic 'incorrect'."""
    feedback = FeedbackInput(
        target_type="account",
        target_id="acct-1",
        rating="WRONG_IDENTITY",
        reason="This domain belongs to a different Acme.",
    )

    assert feedback.rating == "WRONG_IDENTITY"


def test_wrong_identity_requires_a_reason() -> None:
    """Negative corrections must say why, or they cannot be acted on."""
    with pytest.raises(ValidationError):
        FeedbackInput(
            target_type="account", target_id="acct-1", rating="WRONG_IDENTITY"
        )


@pytest.mark.parametrize(
    "rating", ["BAD_ACCOUNT", "IRRELEVANT_SIGNAL", "INCORRECT", "WRONG_IDENTITY"]
)
def test_every_negative_rating_requires_a_reason(rating: str) -> None:
    with pytest.raises(ValidationError):
        FeedbackInput(target_type="account", target_id="acct-1", rating=rating)  # type: ignore[arg-type]


def test_positive_ratings_do_not_require_a_reason() -> None:
    FeedbackInput(target_type="account", target_id="acct-1", rating="GOOD_ACCOUNT")
