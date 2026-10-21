"""The offline demo must show every outcome, and must not fake any of them.

The demo is the first thing a new user sees. It should walk them through each
state an account can reach -- ready, under-researched, no signal, identity
conflict -- while still running on the real scoring and entity-safety code, so
the demo cannot drift into showing behaviour the product does not have.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.app.main import app
from apps.api.app.repositories.fixture import FixtureRepository

client = TestClient(app)


def _demo() -> FixtureRepository:
    return FixtureRepository()


def test_every_brief_state_is_shown() -> None:
    states = {account.brief_state for account in _demo().accounts.values()}

    assert states == {
        "FOUNDER_READY",
        "RESEARCH_CANDIDATE",
        "MONITOR",
        "IDENTITY_REVIEW_REQUIRED",
    }


def test_every_company_is_invented_and_labelled() -> None:
    repo = _demo()
    for account in repo.accounts.values():
        assert account.domain.endswith((".example", ".test")), account.domain
        brief = repo.briefs[account.id]
        assert all(source.demo_data for source in brief.sources)
        assert any("DEMO DATA" in risk for risk in brief.risks)


def test_only_founder_ready_accounts_carry_a_draft() -> None:
    repo = _demo()
    for account in repo.accounts.values():
        draft = repo.briefs[account.id].campaign
        if account.brief_state == "FOUNDER_READY":
            assert draft.body and draft.evidence_ids
            assert account.priority_band == "HIGH"
        else:
            assert not draft.body


def test_unknown_fit_is_shown_as_unknown_not_zero() -> None:
    brightwave = next(a for a in _demo().accounts.values() if a.name == "Brightwave Analytics")

    assert brightwave.scores.fit.determined is False
    assert brightwave.scores.intent.score > 0


def test_lookalike_evidence_is_rejected_by_the_real_gate() -> None:
    repo = _demo()
    quillfront = next(a for a in repo.accounts.values() if a.name == "Quillfront")
    rejected = repo.briefs[quillfront.id].rejected_or_ambiguous_evidence

    decisions = {item["source_domain"]: item["decision"] for item in rejected}
    assert decisions == {
        "quillfront.test": "UNATTACHED_ENTITY_AMBIGUOUS",
        "quillfrontgroup.example": "RELATED_ENTITY_ONLY",
    }
    # The held-back funding round must not become a signal or raise intent.
    assert not repo.briefs[quillfront.id].current_signals
    assert quillfront.scores.intent.score == 0


def test_approval_count_only_counts_drafts_that_can_be_approved() -> None:
    from apps.api.app.repositories.fixture import repository

    body = client.get("/api/v1/bootstrap", headers={"X-Demo-User": "demo-count"}).json()
    workspace_briefs = [
        brief
        for brief in repository.briefs.values()
        if brief.account.workspace_id == body["workspace"]["id"]
    ]
    approvable = [
        brief
        for brief in workspace_briefs
        if brief.brief_state == "FOUNDER_READY" and brief.campaign.status == "draft"
    ]
    placeholders = [
        brief
        for brief in workspace_briefs
        if brief.brief_state != "FOUNDER_READY" and brief.campaign.status == "draft"
    ]

    # Placeholder drafts exist, and the badge must not count them.
    assert placeholders
    assert body["approval_count"] == len(approvable)


def test_demo_import_keeps_owner_and_tags() -> None:
    from apps.api.app.domain.models import AccountImportRecord, AccountImportSource

    repo = _demo()
    icp = next(item for item in repo.icps.values() if item.selected)
    imported, _ = repo.import_accounts(
        icp.workspace_id,
        icp.id,
        [AccountImportRecord(company_name="PostHog", domain="posthog.com", owner="Asha", tags=["example"])],
        AccountImportSource.CSV_UPLOAD,
    )

    assert imported[0].owner == "Asha"
    assert imported[0].tags == ["example"]
