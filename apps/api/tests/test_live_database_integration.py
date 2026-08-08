from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from pydantic import HttpUrl
from sqlalchemy import select

from apps.api.app.db.models import EvidenceFactRow, SourceDocumentRow
from apps.api.app.db.session import SessionFactory, dispose_engine
from apps.api.app.domain.models import (
    AccountImportRecord,
    AccountImportSource,
    FeedbackInput,
    ProductMode,
    QAEvaluationInput,
)
from apps.api.app.jobs.queue import ResearchJob, decode_job, enqueue_job
from apps.api.app.providers.live import LiveResearchProvider
from apps.api.app.repositories.postgres import repository
from apps.api.app.services.live_research import (
    discover_accounts,
    execute_research,
    research_account,
)
from services.research_gateway.app.schemas import (
    SearchResponse,
    SearchResult,
    SourceDocumentInput,
)
from redis.asyncio import Redis


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_DB_TESTS") != "1",
    reason="Set RUN_LIVE_DB_TESTS=1 with migrated PostgreSQL to run",
)


@pytest_asyncio.fixture(autouse=True)
async def isolate_async_database_pool() -> None:
    yield
    await dispose_engine()


class ControlledPublicTransport(LiveResearchProvider):
    """Test transport only; it is never selected by production settings."""

    async def search(
        self,
        *,
        workspace_id: str,
        research_run_id: str,
        query: str,
        limit: int = 5,
        freshness_days: int | None = 365,
        purpose: str = "market_research",
    ) -> SearchResponse:
        del workspace_id, research_run_id, limit, freshness_days
        if purpose == "news":
            return SearchResponse(
                status="completed",
                backend="controlled-integration-transport",
                results=[],
            )
        if purpose in {"account_discovery", "account_research"}:
            url = HttpUrl(
                "https://verified-software.example/"
                if purpose == "account_discovery"
                else "https://verified-software.example/about"
            )
            return SearchResponse(
                status="completed",
                backend="controlled-integration-transport",
                results=[
                    SearchResult(
                        url=url,
                        canonical_url=url,
                        title="Verified Software Company",
                        snippet=(
                            "India B2B SaaS enterprise software with a 180 employee "
                            "team and a growing customer support operation."
                        ),
                        backend="controlled-integration-transport",
                    )
                ],
            )
        suffix = abs(hash(query)) % 10_000
        url = HttpUrl(f"https://verified-{suffix}.example/company")
        return SearchResponse(
            status="completed",
            backend="controlled-integration-transport",
            results=[
                SearchResult(
                    url=url,
                    canonical_url=url,
                    title=f"Verified {suffix} Software",
                    snippet="A public company description and launch update.",
                    backend="controlled-integration-transport",
                )
            ],
        )

    async def fetch(
        self,
        *,
        workspace_id: str,
        research_run_id: str,
        url: str,
    ) -> SourceDocumentInput:
        del workspace_id, research_run_id
        return SourceDocumentInput(
            platform="web",
            source_type="webpage",
            backend="controlled-integration-transport",
            url=HttpUrl(url),
            canonical_url=HttpUrl(url),
            title="Verified Software Company",
            published_at=datetime.now(UTC),
            content_type="text/html",
            text=(
                "Verified Software Company is an India B2B SaaS enterprise software "
                "platform for founder-led teams. Our team has 180 employees. Its "
                "customer support operation handles technical support for a growing "
                "customer base. The company launched a new product for revenue teams "
                "and is hiring go-to-market specialists."
            ),
            metadata={"test_transport": True},
        )


class EmptyPublicTransport(LiveResearchProvider):
    async def search(
        self,
        *,
        workspace_id: str,
        research_run_id: str,
        query: str,
        limit: int = 5,
        freshness_days: int | None = 365,
        purpose: str = "market_research",
    ) -> SearchResponse:
        del workspace_id, research_run_id, query, limit, freshness_days, purpose
        return SearchResponse(
            status="completed",
            backend="controlled-empty-transport",
            results=[],
        )


class ProviderIndependentByoaTransport(ControlledPublicTransport):
    async def search(
        self,
        *args: object,
        **kwargs: object,
    ) -> SearchResponse:
        del args, kwargs
        raise AssertionError("BYOA official-domain research must not call search")


@pytest.mark.asyncio
async def test_redis_job_contract_round_trip() -> None:
    redis = Redis.from_url("redis://127.0.0.1:6379/0", decode_responses=True)
    await redis.delete("gtm:research-jobs")
    job = ResearchJob(
        kind="research",
        workspace_id=str(uuid4()),
        target_id=str(uuid4()),
        actor_id="integration-user",
    )
    try:
        await enqueue_job(job)
        raw = await redis.lpop("gtm:research-jobs")
        assert raw is not None
        assert decode_job(raw) == job
    finally:
        await redis.delete("gtm:research-jobs")
        await redis.aclose()


@pytest.mark.asyncio
async def test_byoa_import_to_brief_without_search_provider() -> None:
    user_id = f"byoa-integration-{uuid4().hex}"
    async with SessionFactory() as session:
        workspace = await repository.create_workspace(
            session, user_id, "BYOA integration workspace"
        )
        product = await repository.create_product(
            session,
            workspace.id,
            user_id,
            company_name="BYOA Control",
            website="https://byoa-control.com",
            product="Evidence-backed GTM intelligence",
            target_market="Founder-led B2B SaaS teams in India",
        )
        run = await repository.create_run(
            session,
            workspace.id,
            user_id,
            product.id,
            {"max_searches": 0, "max_documents": 8},
            ProductMode.BYOA_CORE,
        )
        icp = await repository.initialize_byoa_run(
            session,
            run.id,
            workspace.id,
            user_id,
        )
        imported, duplicates = await repository.import_accounts(
            session,
            workspace_id=workspace.id,
            actor_id=user_id,
            icp_id=icp.id,
            records=[
                AccountImportRecord(
                    company_name="Verified Software Company",
                    domain="verified-software.com",
                )
            ],
            import_source=AccountImportSource.API,
        )
        assert len(imported) == 1
        assert duplicates == []
        account_id = str(imported[0].id)

    await research_account(account_id, ProviderIndependentByoaTransport())

    async with SessionFactory() as session:
        accounts = await repository.list_accounts(session, workspace.id)
        account = next(item for item in accounts if item.id == account_id)
        assert account.product_mode == ProductMode.BYOA_CORE
        assert account.provenance == "IMPORTED"
        assert account.import_source == AccountImportSource.API
        assert account.domain == "verified-software.com"
        assert account.evidence_ids
        brief = await repository.brief(session, workspace.id, account_id)
        assert brief is not None
        assert brief.verified_identity["canonical_registrable_domain"] == (
            "verified-software.com"
        )
        assert brief.sources
        assert brief.verified_facts
        assert all(not source.demo_data for source in brief.sources)


@pytest.mark.asyncio
async def test_durable_research_to_ranked_account_flow() -> None:
    user_id = f"integration-{uuid4().hex}"
    async with SessionFactory() as session:
        workspace = await repository.create_workspace(
            session, user_id, "Live integration workspace"
        )
        product = await repository.create_product(
            session,
            workspace.id,
            user_id,
            company_name="Kubu Works",
            website="https://kubuworks.com",
            product="Evidence-backed GTM intelligence",
            target_market="Founder-led B2B SaaS teams in India",
        )
        run = await repository.create_run(
            session,
            workspace.id,
            user_id,
            product.id,
            {"max_searches": 4, "max_documents": 8},
        )

    transport = ControlledPublicTransport()
    await execute_research(run.id, transport)

    async with SessionFactory() as session:
        run_row = await repository.run_row(session, run.id, workspace.id)
        assert run_row is not None
        durable_run = await repository.run_domain(session, run_row)
        assert durable_run.status == "awaiting_icp"
        assert durable_run.documents_used > 0
        assert durable_run.findings
        assert all(item.evidence_ids for item in durable_run.findings)
        icps = await repository.list_icps(session, workspace.id)
        assert len(icps) == 3
        selected = await repository.select_icp(
            session, workspace.id, user_id, icps[0].id
        )

    await discover_accounts(selected.id, transport)

    async with SessionFactory() as session:
        refreshed_run = await repository.run_row(session, run.id, workspace.id)
        assert refreshed_run is not None
        assert refreshed_run.status == "completed", refreshed_run.error
        accounts = await repository.list_accounts(session, workspace.id)
        assert accounts
        assert accounts == sorted(
            accounts, key=lambda item: item.scores.priority, reverse=True
        )
        brief = await repository.brief(session, workspace.id, accounts[0].id)
        assert brief is not None
        assert brief.sources
        assert all(not source.demo_data for source in brief.sources)
        evidence_ids = {item.id for item in brief.evidence}
        assert all(
            set(claim.evidence_ids).issubset(evidence_ids)
            for claim in [*brief.why_it_fits, *brief.why_now]
        )
        source_rows = (
            await session.scalars(
                select(SourceDocumentRow).where(
                    SourceDocumentRow.workspace_id == UUID(workspace.id)
                )
            )
        ).all()
        facts = (
            await session.scalars(
                select(EvidenceFactRow).where(
                    EvidenceFactRow.workspace_id == UUID(workspace.id)
                )
            )
        ).all()
        sources = {row.id: row for row in source_rows}
        assert facts
        assert all(
            fact.passage in sources[fact.source_id].cleaned_text for fact in facts
        )
        feedback = await repository.create_feedback(
            session,
            workspace.id,
            user_id,
            FeedbackInput(
                target_type="account",
                target_id=accounts[0].id,
                rating="GOOD_ACCOUNT",
                reason="Live integration persistence check",
            ),
        )
        qa = await repository.create_qa_evaluation(
            session,
            workspace.id,
            user_id,
            QAEvaluationInput(
                research_run_id=run.id,
                account_id=accounts[0].id,
                company_validity="REAL",
                domain_correctness="CORRECT",
                icp_relevance=3,
                evidence_correctness="SUPPORTED",
                signal_relevance=0,
                brief_usefulness=2,
                evidence_links_working=True,
                unsupported_important_claim=False,
                notes="Controlled live integration record",
            ),
        )
        assert feedback.workspace_id == workspace.id
        assert qa.research_run_id == run.id
        assert qa.account_id == accounts[0].id

    user_id = f"no-results-{uuid4().hex}"
    async with SessionFactory() as session:
        workspace = await repository.create_workspace(
            session,
            user_id,
            "No relevant results workspace",
        )
        product = await repository.create_product(
            session,
            workspace.id,
            user_id,
            company_name="No Results Control",
            website="https://example.com",
            product="Public research control",
            target_market="Narrow public research topic",
        )
        run = await repository.create_run(
            session,
            workspace.id,
            user_id,
            product.id,
            {"max_searches": 4, "max_documents": 8},
        )

    await execute_research(run.id, EmptyPublicTransport())

    async with SessionFactory() as session:
        run_row = await repository.run_row(session, run.id, workspace.id)
        assert run_row is not None
        assert run_row.status == "completed"
        assert run_row.current_stage == "no_relevant_results"
        assert run_row.documents_used == 0
        assert run_row.evidence_count == 0
        assert run_row.error is None
        assert await repository.list_icps(session, workspace.id) == []
