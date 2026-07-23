from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Select, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.db.models import (
    AccountRow,
    AccountScoreSnapshotRow,
    AuditEventRow,
    CampaignDraftRow,
    EvidenceFactRow,
    GTMFindingRow,
    ICPProfileRow,
    MembershipRow,
    OpportunityBriefRow,
    ProductProfileRow,
    ResearchRunRow,
    SourceDocumentRow,
    WorkspaceRow,
)
from apps.api.app.domain.models import (
    Account,
    AccountOpportunityBrief,
    AccountScores,
    AuditEvent,
    CampaignDraft,
    ClaimStatus,
    EvidenceFact,
    Finding,
    ICP,
    ProductProfile,
    ResearchRun,
    SourceDocument,
    Workspace,
)
from pydantic import HttpUrl


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise KeyError("Resource not found") from exc


def _now() -> datetime:
    return datetime.now(UTC)


def _string_list(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


class PostgresRepository:
    async def resolve_membership(
        self, session: AsyncSession, user_id: str, workspace_id: str | None
    ) -> MembershipRow | None:
        statement: Select[tuple[MembershipRow]] = select(MembershipRow).where(
            MembershipRow.user_id == user_id
        )
        if workspace_id:
            statement = statement.where(MembershipRow.workspace_id == _uuid(workspace_id))
        statement = statement.order_by(MembershipRow.workspace_id).limit(1)
        return await session.scalar(statement)

    async def create_workspace(
        self, session: AsyncSession, user_id: str, name: str
    ) -> Workspace:
        row = WorkspaceRow(name=name)
        session.add(row)
        await session.flush()
        session.add(
            MembershipRow(workspace_id=row.id, user_id=user_id, role="owner")
        )
        await self.record(
            session,
            row.id,
            user_id,
            "workspace_created",
            "workspace",
            str(row.id),
        )
        await session.commit()
        await session.refresh(row)
        return Workspace(id=str(row.id), name=row.name, created_at=row.created_at)

    async def workspace(
        self, session: AsyncSession, workspace_id: str
    ) -> Workspace | None:
        row = await session.get(WorkspaceRow, _uuid(workspace_id))
        if row is None:
            return None
        return Workspace(id=str(row.id), name=row.name, created_at=row.created_at)

    async def create_product(
        self,
        session: AsyncSession,
        workspace_id: str,
        actor_id: str,
        *,
        company_name: str,
        website: str,
        product: str,
        target_market: str,
    ) -> ProductProfile:
        row = ProductProfileRow(
            workspace_id=_uuid(workspace_id),
            company_name=company_name,
            website=website,
            product=product,
            target_market=target_market,
            status="confirmed",
            profile_data={"input_classification": "user_confirmed"},
        )
        session.add(row)
        await session.flush()
        await self.record(
            session,
            row.workspace_id,
            actor_id,
            "product_confirmed",
            "product",
            str(row.id),
        )
        await session.commit()
        await session.refresh(row)
        return self.product_domain(row)

    async def latest_product(
        self, session: AsyncSession, workspace_id: str
    ) -> ProductProfileRow | None:
        return await session.scalar(
            select(ProductProfileRow)
            .where(ProductProfileRow.workspace_id == _uuid(workspace_id))
            .order_by(desc(ProductProfileRow.created_at))
            .limit(1)
        )

    async def create_run(
        self,
        session: AsyncSession,
        workspace_id: str,
        actor_id: str,
        product_id: str,
        budgets: dict[str, object],
    ) -> ResearchRun:
        product = await session.get(ProductProfileRow, _uuid(product_id))
        if product is None or str(product.workspace_id) != workspace_id:
            raise KeyError("Product not found")
        row = ResearchRunRow(
            workspace_id=product.workspace_id,
            product_id=product.id,
            status="queued",
            current_stage="research_plan",
            budgets=budgets,
            error=None,
            trace_id=uuid.uuid4().hex,
            searches_used=0,
            documents_used=0,
            evidence_count=0,
        )
        session.add(row)
        await session.flush()
        await self.record(
            session,
            product.workspace_id,
            actor_id,
            "research_run_started",
            "research_run",
            str(row.id),
        )
        await session.commit()
        await session.refresh(row)
        return await self.run_domain(session, row)

    async def run_row(
        self, session: AsyncSession, run_id: str, workspace_id: str | None = None
    ) -> ResearchRunRow | None:
        row = await session.get(ResearchRunRow, _uuid(run_id))
        if row is not None and workspace_id and str(row.workspace_id) != workspace_id:
            return None
        return row

    async def latest_run(
        self, session: AsyncSession, workspace_id: str
    ) -> ResearchRunRow | None:
        return await session.scalar(
            select(ResearchRunRow)
            .where(ResearchRunRow.workspace_id == _uuid(workspace_id))
            .order_by(desc(ResearchRunRow.created_at))
            .limit(1)
        )

    async def run_domain(
        self, session: AsyncSession, row: ResearchRunRow
    ) -> ResearchRun:
        findings = list(
            (
                await session.scalars(
                    select(GTMFindingRow)
                    .where(GTMFindingRow.research_run_id == row.id)
                    .order_by(GTMFindingRow.created_at)
                )
            ).all()
        )
        return ResearchRun(
            id=str(row.id),
            workspace_id=str(row.workspace_id),
            product_id=str(row.product_id),
            status=row.status,  # type: ignore[arg-type]
            current_stage=row.current_stage,
            started_at=row.created_at,
            updated_at=row.updated_at,
            completed_at=row.completed_at,
            error=row.error,
            searches_used=row.searches_used,
            documents_used=row.documents_used,
            findings=[
                Finding(
                    id=str(item.id),
                    category=item.category,  # type: ignore[arg-type]
                    claim=item.claim,
                    confidence=item.confidence,
                    status=ClaimStatus(item.status),
                    evidence_ids=item.evidence_ids,
                )
                for item in findings
            ],
        )

    async def list_icps(
        self, session: AsyncSession, workspace_id: str
    ) -> list[ICP]:
        rows = (
            await session.scalars(
                select(ICPProfileRow)
                .where(ICPProfileRow.workspace_id == _uuid(workspace_id))
                .order_by(ICPProfileRow.created_at)
            )
        ).all()
        return [self.icp_domain(row) for row in rows]

    async def icp_row(
        self, session: AsyncSession, icp_id: str, workspace_id: str
    ) -> ICPProfileRow | None:
        row = await session.get(ICPProfileRow, _uuid(icp_id))
        if row is None or str(row.workspace_id) != workspace_id:
            return None
        return row

    async def select_icp(
        self,
        session: AsyncSession,
        workspace_id: str,
        actor_id: str,
        icp_id: str,
    ) -> ICP:
        selected = await self.icp_row(session, icp_id, workspace_id)
        if selected is None:
            raise KeyError("ICP not found")
        rows = (
            await session.scalars(
                select(ICPProfileRow).where(
                    ICPProfileRow.research_run_id == selected.research_run_id
                )
            )
        ).all()
        now = _now()
        for row in rows:
            row.selected_at = now if row.id == selected.id else None
        await self.record(
            session,
            selected.workspace_id,
            actor_id,
            "icp_selected",
            "icp",
            str(selected.id),
        )
        await session.commit()
        return self.icp_domain(selected)

    async def list_accounts(
        self, session: AsyncSession, workspace_id: str
    ) -> list[Account]:
        rows = (
            await session.scalars(
                select(AccountRow)
                .where(AccountRow.workspace_id == _uuid(workspace_id))
                .order_by(desc(AccountRow.last_researched_at))
            )
        ).all()
        accounts: list[Account] = []
        for row in rows:
            account = await self.account_domain(session, row)
            if account is not None:
                accounts.append(account)
        return sorted(accounts, key=lambda item: item.scores.priority, reverse=True)

    async def account_domain(
        self, session: AsyncSession, row: AccountRow
    ) -> Account | None:
        snapshot = await session.scalar(
            select(AccountScoreSnapshotRow)
            .where(AccountScoreSnapshotRow.account_id == row.id)
            .order_by(desc(AccountScoreSnapshotRow.created_at))
            .limit(1)
        )
        if snapshot is None or row.icp_profile_id is None:
            return None
        scores = AccountScores.model_validate(snapshot.scores)
        return Account(
            id=str(row.id),
            workspace_id=str(row.workspace_id),
            icp_id=str(row.icp_profile_id),
            name=row.name,
            domain=row.domain,
            industry=row.industry or "Unverified",
            location=row.location or "Unverified",
            employee_band=row.employee_band or "Unverified",
            scores=scores,
            top_signal=str(row.attributes.get("top_signal") or "No verified current signal"),
            recommended_action=str(
                row.attributes.get("recommended_action")
                or "Review public evidence before outreach"
            ),
            last_researched_at=row.last_researched_at or row.created_at,
        )

    async def brief(
        self, session: AsyncSession, workspace_id: str, account_id: str
    ) -> AccountOpportunityBrief | None:
        account_row = await session.get(AccountRow, _uuid(account_id))
        if account_row is None or str(account_row.workspace_id) != workspace_id:
            return None
        account = await self.account_domain(session, account_row)
        if account is None:
            return None
        brief_row = await session.scalar(
            select(OpportunityBriefRow)
            .where(OpportunityBriefRow.account_id == account_row.id)
            .order_by(desc(OpportunityBriefRow.version))
            .limit(1)
        )
        if brief_row is None:
            return None
        campaign_row = await session.scalar(
            select(CampaignDraftRow)
            .where(CampaignDraftRow.opportunity_brief_id == brief_row.id)
            .order_by(desc(CampaignDraftRow.created_at))
            .limit(1)
        )
        if campaign_row is None:
            return None
        payload = dict(brief_row.payload)
        payload["account"] = account.model_dump(mode="json")
        payload["campaign"] = CampaignDraft(
            id=str(campaign_row.id),
            account_id=str(account_row.id),
            subject=campaign_row.subject,
            body=campaign_row.body,
            status=campaign_row.status,  # type: ignore[arg-type]
            evidence_ids=campaign_row.evidence_ids,
            updated_at=campaign_row.updated_at,
        ).model_dump(mode="json")
        return AccountOpportunityBrief.model_validate(payload)

    async def campaign(
        self, session: AsyncSession, workspace_id: str, campaign_id: str
    ) -> CampaignDraftRow | None:
        row = await session.get(CampaignDraftRow, _uuid(campaign_id))
        if row is None or str(row.workspace_id) != workspace_id:
            return None
        return row

    async def approval_count(
        self, session: AsyncSession, workspace_id: str
    ) -> int:
        rows = (
            await session.scalars(
                select(CampaignDraftRow).where(
                    CampaignDraftRow.workspace_id == _uuid(workspace_id),
                    CampaignDraftRow.status == "draft",
                )
            )
        ).all()
        return len(rows)

    async def audit(
        self, session: AsyncSession, workspace_id: str
    ) -> list[AuditEvent]:
        rows = (
            await session.scalars(
                select(AuditEventRow)
                .where(AuditEventRow.workspace_id == _uuid(workspace_id))
                .order_by(AuditEventRow.created_at)
            )
        ).all()
        return [
            AuditEvent(
                id=str(row.id),
                workspace_id=str(row.workspace_id),
                actor_id=row.actor_id,
                event_type=row.event_type,
                target_type=row.target_type,
                target_id=row.target_id,
                occurred_at=row.created_at,
                metadata={key: str(value) for key, value in row.payload.items()},
            )
            for row in rows
        ]

    async def record(
        self,
        session: AsyncSession,
        workspace_id: uuid.UUID,
        actor_id: str,
        event_type: str,
        target_type: str,
        target_id: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        session.add(
            AuditEventRow(
                workspace_id=workspace_id,
                actor_id=actor_id,
                event_type=event_type,
                target_type=target_type,
                target_id=target_id,
                payload=payload or {},
            )
        )

    @staticmethod
    def product_domain(row: ProductProfileRow) -> ProductProfile:
        return ProductProfile(
            id=str(row.id),
            workspace_id=str(row.workspace_id),
            company_name=row.company_name,
            website=row.website,
            product=row.product,
            target_market=row.target_market,
            status=row.status,  # type: ignore[arg-type]
            created_at=row.created_at,
        )

    @staticmethod
    def icp_domain(row: ICPProfileRow) -> ICP:
        definition = row.definition
        firmographics = definition.get("firmographics", [])
        pains = definition.get("pains", [])
        triggers = definition.get("triggers", [])
        return ICP(
            id=str(row.id),
            workspace_id=str(row.workspace_id),
            research_run_id=str(row.research_run_id),
            name=row.name,
            description=row.description,
            firmographics=_string_list(firmographics),
            pains=_string_list(pains),
            triggers=_string_list(triggers),
            rationale=str(definition.get("rationale") or ""),
            evidence_ids=row.evidence_ids,
            selected=row.selected_at is not None,
        )

    @staticmethod
    def source_domain(row: SourceDocumentRow) -> SourceDocument:
        return SourceDocument(
            id=str(row.id),
            workspace_id=str(row.workspace_id),
            platform=row.platform,
            source_type=row.source_type,
            backend=row.backend,
            url=HttpUrl(row.url),
            canonical_url=HttpUrl(row.canonical_url),
            title=row.title,
            published_at=row.published_at,
            retrieved_at=row.retrieved_at,
            permission_classification=row.permission_classification,
            trust_score=row.trust_score,
            demo_data=False,
        )

    @staticmethod
    def evidence_domain(row: EvidenceFactRow) -> EvidenceFact:
        return EvidenceFact(
            id=str(row.id),
            workspace_id=str(row.workspace_id),
            source_id=str(row.source_id),
            passage=row.passage,
            claim=row.claim,
            confidence=float(row.confidence),
            status=ClaimStatus(row.status),
            observed_at=row.observed_at,
        )


repository = PostgresRepository()
