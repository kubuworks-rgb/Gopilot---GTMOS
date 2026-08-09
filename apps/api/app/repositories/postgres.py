from __future__ import annotations

import uuid
import re
from datetime import UTC, datetime

from sqlalchemy import Select, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.db.models import (
    AccountRow,
    AccountScoreSnapshotRow,
    AuditEventRow,
    CampaignDraftRow,
    EvidenceFactRow,
    FeedbackEventRow,
    GTMFindingRow,
    ICPProfileRow,
    MembershipRow,
    OpportunityBriefRow,
    ProductProfileRow,
    QAEvaluationRow,
    ResearchRunRow,
    SourceDocumentRow,
    WorkspaceRow,
)
from apps.api.app.domain.models import (
    Account,
    AccountImportRecord,
    AccountImportSource,
    AccountOpportunityBrief,
    AccountScores,
    AccountReviewEntry,
    AccountReviewStatus,
    AuditEvent,
    CampaignDraft,
    ClaimStatus,
    EvidenceFact,
    FeedbackInput,
    FeedbackRecord,
    Finding,
    ICP,
    ProductProfile,
    ProductMode,
    ProfileClaim,
    ProvenanceStatus,
    QualificationStatus,
    QAEvaluationInput,
    QAEvaluationRecord,
    CompanySizeStatus,
    ResearchRun,
    SourceDocument,
    Workspace,
)
from apps.api.app.services.entity_resolution import IMPORT_PENDING_IDENTITY_WARNING
from apps.api.app.services.scoring import score_account
from pydantic import HttpUrl


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise KeyError("Resource not found") from exc


def _now() -> datetime:
    return datetime.now(UTC)


def _review_history(attributes: dict[str, object]) -> list[AccountReviewEntry]:
    raw = attributes.get("review_history")
    if not isinstance(raw, list):
        return []
    entries: list[AccountReviewEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            entries.append(AccountReviewEntry.model_validate(item))
        except ValueError:
            # A malformed history entry must not make the account unreadable.
            continue
    return entries


def _input_metadata_value(attributes: dict[str, object], key: str) -> str | None:
    """Read a user-supplied import field, tolerating absence at every level."""
    metadata = attributes.get("input_metadata")
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(key)
    return str(value).strip() or None if value not in (None, "") else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _string_list(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _criteria_list(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    return [
        {str(key): str(item_value) for key, item_value in item.items()}
        for item in value
        if isinstance(item, dict)
    ]


def _product_understanding(
    company_name: str, website: str, product: str, target_market: str
) -> list[dict[str, object]]:
    claims: list[dict[str, object]] = [
        {
            "field": "company_name",
            "value": company_name,
            "status": ProvenanceStatus.USER_CONFIRMED.value,
            "evidence_ids": [],
        },
        {
            "field": "website",
            "value": website,
            "status": ProvenanceStatus.USER_CONFIRMED.value,
            "evidence_ids": [],
        },
        {
            "field": "product",
            "value": product,
            "status": ProvenanceStatus.USER_CONFIRMED.value,
            "evidence_ids": [],
        },
        {
            "field": "target_market",
            "value": target_market,
            "status": ProvenanceStatus.USER_CONFIRMED.value,
            "evidence_ids": [],
        },
    ]
    geography = next(
        (
            name
            for name in ("India", "APAC", "United States", "Europe")
            if name.lower() in target_market.lower()
        ),
        None,
    )
    size_match = re.search(r"\b(\d{1,5})\s*[-–]\s*(\d{1,5})\b", target_market)
    claims.extend(
        [
            {
                "field": "geography",
                "value": geography,
                "status": (
                    ProvenanceStatus.USER_CONFIRMED.value
                    if geography
                    else ProvenanceStatus.UNKNOWN.value
                ),
                "evidence_ids": [],
            },
            {
                "field": "preferred_company_size",
                "value": (
                    f"{size_match.group(1)}-{size_match.group(2)} employees"
                    if size_match
                    else None
                ),
                "status": (
                    ProvenanceStatus.USER_CONFIRMED.value
                    if size_match
                    else ProvenanceStatus.UNKNOWN.value
                ),
                "evidence_ids": [],
            },
            {
                "field": "product_category",
                "value": product.split(".", 1)[0][:240],
                "status": ProvenanceStatus.USER_CONFIRMED.value,
                "evidence_ids": [],
                "rationale": "Category is taken from the user-confirmed product description.",
            },
            {
                "field": "problem_solved",
                "value": "Growing repetitive customer-support workload",
                "status": ProvenanceStatus.INFERRED.value,
                "evidence_ids": [],
                "rationale": "Initial hypothesis derived from the product description.",
            },
            {
                "field": "primary_outcomes",
                "value": (
                    "Reduce repetitive tickets and response time; increase support "
                    "capacity without proportional headcount growth"
                ),
                "status": ProvenanceStatus.INFERRED.value,
                "evidence_ids": [],
                "rationale": "Potential outcomes require customer or product evidence.",
            },
            {
                "field": "business_model",
                "value": "B2B software platform",
                "status": ProvenanceStatus.INFERRED.value,
                "evidence_ids": [],
            },
            {
                "field": "possible_buyer_roles",
                "value": (
                    "Head of Customer Support; Head of CX; COO; Founder; "
                    "VP Customer Success"
                ),
                "status": ProvenanceStatus.INFERRED.value,
                "evidence_ids": [],
            },
            {
                "field": "company_characteristics",
                "value": target_market,
                "status": ProvenanceStatus.USER_CONFIRMED.value,
                "evidence_ids": [],
            },
            {
                "field": "pain_hypotheses",
                "value": (
                    "Support volume grows with customers; repetitive tickets may "
                    "consume specialist capacity"
                ),
                "status": ProvenanceStatus.INFERRED.value,
                "evidence_ids": [],
            },
            {
                "field": "buying_triggers",
                "value": (
                    "Support hiring; customer growth; enterprise expansion; "
                    "new market or product launch"
                ),
                "status": ProvenanceStatus.INFERRED.value,
                "evidence_ids": [],
            },
            {
                "field": "disqualifiers",
                "value": (
                    "Direct support-automation vendor; outside preferred size; "
                    "no B2B SaaS or India evidence"
                ),
                "status": ProvenanceStatus.INFERRED.value,
                "evidence_ids": [],
            },
            {
                "field": "competitors_or_alternatives",
                "value": None,
                "status": ProvenanceStatus.UNKNOWN.value,
                "evidence_ids": [],
            },
            {
                "field": "profile_confidence",
                "value": "Medium before market research",
                "status": ProvenanceStatus.INFERRED.value,
                "evidence_ids": [],
            },
        ]
    )
    return claims


class PostgresRepository:
    async def resolve_membership(
        self, session: AsyncSession, user_id: str, workspace_id: str | None
    ) -> MembershipRow | None:
        statement: Select[tuple[MembershipRow]] = select(MembershipRow).where(
            MembershipRow.user_id == user_id
        )
        if workspace_id:
            statement = statement.where(
                MembershipRow.workspace_id == _uuid(workspace_id)
            )
        statement = statement.order_by(MembershipRow.workspace_id).limit(1)
        return await session.scalar(statement)

    async def create_workspace(
        self, session: AsyncSession, user_id: str, name: str
    ) -> Workspace:
        row = WorkspaceRow(name=name)
        session.add(row)
        await session.flush()
        session.add(MembershipRow(workspace_id=row.id, user_id=user_id, role="owner"))
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
            profile_data={
                "input_classification": "user_confirmed",
                "understanding": _product_understanding(
                    company_name, website, product, target_market
                ),
            },
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
        product_mode: ProductMode = ProductMode.BYOA_CORE,
    ) -> ResearchRun:
        product = await session.get(ProductProfileRow, _uuid(product_id))
        if product is None or str(product.workspace_id) != workspace_id:
            raise KeyError("Product not found")
        row = ResearchRunRow(
            workspace_id=product.workspace_id,
            product_id=product.id,
            status="queued",
            current_stage="research_plan",
            budgets={**budgets, "product_mode": product_mode.value},
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

    async def initialize_byoa_run(
        self,
        session: AsyncSession,
        run_id: str,
        workspace_id: str,
        actor_id: str,
    ) -> ICP:
        run = await self.run_row(session, run_id, workspace_id)
        if run is None:
            raise KeyError("Research run not found")
        product = await session.get(ProductProfileRow, run.product_id)
        if product is None:
            raise KeyError("Product not found")
        existing = await session.scalar(
            select(ICPProfileRow)
            .where(
                ICPProfileRow.research_run_id == run.id,
                ICPProfileRow.workspace_id == run.workspace_id,
            )
            .order_by(ICPProfileRow.created_at)
            .limit(1)
        )
        if existing is None:
            existing = ICPProfileRow(
                workspace_id=run.workspace_id,
                research_run_id=run.id,
                name="Imported account target",
                description=product.target_market,
                definition={
                    "firmographics": [product.target_market],
                    "pains": [],
                    "triggers": [],
                    "rationale": (
                        "User-confirmed target profile for supplied-account research."
                    ),
                    "recommended": True,
                    "qualification_logic": [
                        "Verify identity before scoring",
                        "Unknown criteria remain unknown",
                        "Human approval is required before outbound activity",
                    ],
                    "criteria_version": "byoa-v1",
                    "criteria": [],
                },
                confidence=0.65,
                evidence_ids=[],
                selected_at=_now(),
            )
            session.add(existing)
            await session.flush()
        run.status = "completed"
        run.current_stage = "accounts_import_ready"
        run.completed_at = _now()
        run.updated_at = _now()
        await self.record(
            session,
            run.workspace_id,
            actor_id,
            "byoa_run_ready",
            "research_run",
            str(run.id),
            {"product_mode": ProductMode.BYOA_CORE.value},
        )
        await session.commit()
        await session.refresh(existing)
        return self.icp_domain(existing)

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
            max_searches=_optional_int(row.budgets.get("max_searches")),
            max_documents=_optional_int(row.budgets.get("max_documents")),
            product_mode=ProductMode(
                str(
                    row.budgets.get("product_mode")
                    or ProductMode.BYOA_CORE.value
                )
            ),
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

    async def list_icps(self, session: AsyncSession, workspace_id: str) -> list[ICP]:
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
        raw_company_identity = row.attributes.get("company_identity")
        company_identity: dict[str, object] = (
            {str(key): value for key, value in raw_company_identity.items()}
            if isinstance(raw_company_identity, dict)
            else {}
        )
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
            top_signal=str(
                row.attributes.get("top_signal") or "No verified current signal"
            ),
            recommended_action=str(
                row.attributes.get("recommended_action")
                or "Review public evidence before outreach"
            ),
            last_researched_at=row.last_researched_at or row.created_at,
            qualification_status=QualificationStatus(
                str(
                    row.attributes.get("qualification_status")
                    or QualificationStatus.INSUFFICIENT_EVIDENCE.value
                )
            ),
            qualification_reasons=_string_list(
                row.attributes.get("qualification_reasons")
            ),
            company_size_status=CompanySizeStatus(
                str(
                    row.attributes.get("company_size_status")
                    or CompanySizeStatus.UNKNOWN.value
                )
            ),
            discovery_source=(
                str(row.attributes["discovery_source"])
                if row.attributes.get("discovery_source")
                else None
            ),
            domain_validation=str(row.attributes.get("domain_validation") or "UNKNOWN"),
            evidence_ids=row.evidence_ids,
            source_ids=_string_list(row.attributes.get("source_ids")),
            top_signal_type=(
                str(row.attributes["top_signal_type"])
                if row.attributes.get("top_signal_type")
                else None
            ),
            registrable_domain=(
                str(row.attributes["registrable_domain"])
                if row.attributes.get("registrable_domain")
                else row.domain
            ),
            official_subdomains=_string_list(
                row.attributes.get("official_subdomains")
            ),
            domain_confidence=float(
                str(row.attributes.get("domain_confidence") or 0)
            ),
            qualification_coverage=float(
                str(row.attributes.get("qualification_coverage") or 0)
            ),
            priority_band=str(
                row.attributes.get("priority_band") or "MONITOR"
            ),  # type: ignore[arg-type]
            research_candidate=bool(
                row.attributes.get("research_candidate", True)
            ),
            brief_state=str(
                row.attributes.get("brief_state") or "RESEARCH_CANDIDATE"
            ),  # type: ignore[arg-type]
            company_identity=company_identity,
            product_mode=ProductMode(
                str(
                    row.attributes.get("product_mode")
                    or ProductMode.BYOA_CORE.value
                )
            ),
            import_source=(
                AccountImportSource(str(row.attributes["import_source"]))
                if row.attributes.get("import_source")
                else None
            ),
            provenance=str(
                row.attributes.get("provenance") or "DISCOVERED"
            ),  # type: ignore[arg-type]
            review_status=AccountReviewStatus(
                str(
                    row.attributes.get("review_status")
                    or AccountReviewStatus.PENDING.value
                )
            ),
            owner=_input_metadata_value(row.attributes, "owner"),
            review_history=_review_history(row.attributes),
        )

    async def import_accounts(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        actor_id: str,
        icp_id: str,
        records: list[AccountImportRecord],
        import_source: AccountImportSource,
    ) -> tuple[list[AccountRow], list[str]]:
        icp = await self.icp_row(session, icp_id, workspace_id)
        if icp is None or icp.selected_at is None:
            raise KeyError("Select an ICP before importing accounts")
        workspace_uuid = _uuid(workspace_id)
        existing_domains = set(
            (
                await session.scalars(
                    select(AccountRow.domain).where(
                        AccountRow.workspace_id == workspace_uuid,
                        AccountRow.domain.in_([record.domain for record in records]),
                    )
                )
            ).all()
        )
        imported: list[AccountRow] = []
        duplicates: list[str] = []
        empty_scores = score_account(
            industry_match=0,
            size_match=None,
            geography_match=0,
            signal_strength=0,
            signal_recency=0,
            evidence_coverage=0,
            source_quality=0,
            fit_evidence=[],
            signal_evidence=[],
        )
        for record in records:
            if record.domain in existing_domains:
                duplicates.append(record.domain)
                continue
            row = AccountRow(
                workspace_id=workspace_uuid,
                icp_id=None,
                icp_profile_id=icp.id,
                name=record.company_name,
                domain=record.domain,
                description=record.notes,
                industry=record.industry,
                location=record.country,
                employee_band=record.employee_band,
                business_model=None,
                attributes={
                    "product_mode": ProductMode.BYOA_CORE.value,
                    "import_source": import_source.value,
                    "provenance": "IMPORTED",
                    "review_status": AccountReviewStatus.PENDING.value,
                    "qualification_status": (
                        QualificationStatus.INSUFFICIENT_EVIDENCE.value
                    ),
                    "qualification_reasons": [
                        "Imported account awaits official-site research."
                    ],
                    "company_size_status": CompanySizeStatus.UNKNOWN.value,
                    "domain_validation": "CANONICALIZED_UNVERIFIED",
                    "registrable_domain": record.domain,
                    "domain_confidence": 0.55,
                    "qualification_coverage": 0.0,
                    "priority_band": "MONITOR",
                    "research_candidate": True,
                    "brief_state": "RESEARCH_CANDIDATE",
                    "source_ids": [],
                    "top_signal": "No verified current signal",
                    "recommended_action": (
                        "Research official sources before changing status."
                    ),
                    "input_metadata": {
                        "industry": record.industry,
                        "country": record.country,
                        "employee_band": record.employee_band,
                        "notes": record.notes,
                        "crm_id": record.crm_id,
                        "owner": record.owner,
                        "tags": record.tags,
                    },
                    "company_identity": {
                        "canonical_company_name": record.company_name,
                        "canonical_registrable_domain": record.domain,
                        "verified_official_domains": [],
                        "known_aliases": [],
                        "legal_name": None,
                        "product_names": [],
                        "product_domains": [],
                        "parent_organization": None,
                        "subsidiaries": [],
                        "relationship_evidence_ids": [],
                        "identity_confidence": 0.55,
                        "unresolved_identity_warnings": [
                            IMPORT_PENDING_IDENTITY_WARNING
                        ],
                    },
                },
                evidence_ids=[],
                last_researched_at=_now(),
            )
            session.add(row)
            await session.flush()
            session.add(
                AccountScoreSnapshotRow(
                    workspace_id=workspace_uuid,
                    account_id=row.id,
                    research_run_id=icp.research_run_id,
                    scoring_version="byoa-import-v1",
                    scores=empty_scores.model_dump(mode="json"),
                    weights={},
                    inputs={"status": "awaiting_official_research"},
                )
            )
            await session.flush()
            account_domain = await self.account_domain(session, row)
            if account_domain is None:
                raise RuntimeError("Imported account score snapshot was not persisted")
            raw_identity = row.attributes.get("company_identity")
            verified_identity = (
                {str(key): value for key, value in raw_identity.items()}
                if isinstance(raw_identity, dict)
                else {}
            )
            draft_id = uuid.uuid4()
            placeholder_brief = AccountOpportunityBrief(
                account=account_domain,
                why_it_fits=[],
                why_now=[],
                pain_hypotheses=[],
                recommended_problem=(
                    "Official company evidence has not been collected yet."
                ),
                recommended_offer="No outreach recommendation",
                recommended_action="Research official sources before changing status.",
                risks=["Identity and ICP criteria remain unverified."],
                evidence=[],
                sources=[],
                signals=[],
                campaign=CampaignDraft(
                    id=str(draft_id),
                    account_id=str(row.id),
                    subject="",
                    body="",
                    status="draft",
                    evidence_ids=[],
                ),
                verified_facts=[],
                unknowns=[
                    "Official company identity",
                    "ICP fit",
                    "Current supported signal",
                ],
                research_candidate=True,
                brief_state="RESEARCH_CANDIDATE",
                verified_identity=verified_identity,
                verified_icp_facts=[],
                unknown_icp_facts=[
                    "Industry",
                    "Geography",
                    "Employee size",
                    "Business model",
                ],
                current_signals=[],
                rejected_or_ambiguous_evidence=[],
                hypotheses=[],
                reason_not_to_target=None,
                next_research_step="Fetch and verify the supplied official domain.",
            )
            brief_row = OpportunityBriefRow(
                workspace_id=workspace_uuid,
                account_id=row.id,
                research_run_id=icp.research_run_id,
                payload=placeholder_brief.model_dump(mode="json"),
                evidence_ids=[],
                version=1,
            )
            session.add(brief_row)
            await session.flush()
            session.add(
                CampaignDraftRow(
                    id=draft_id,
                    workspace_id=workspace_uuid,
                    account_id=row.id,
                    opportunity_brief_id=brief_row.id,
                    subject="",
                    body="",
                    status="draft",
                    evidence_ids=[],
                    risk_flags=placeholder_brief.risks,
                    updated_at=_now(),
                )
            )
            await self.record(
                session,
                workspace_uuid,
                actor_id,
                "account_imported",
                "account",
                str(row.id),
                {
                    "import_source": import_source.value,
                    "canonical_domain": record.domain,
                },
            )
            existing_domains.add(record.domain)
            imported.append(row)
        await session.commit()
        for row in imported:
            await session.refresh(row)
        return imported, sorted(set(duplicates))

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

    async def approval_count(self, session: AsyncSession, workspace_id: str) -> int:
        rows = (
            await session.scalars(
                select(CampaignDraftRow).where(
                    CampaignDraftRow.workspace_id == _uuid(workspace_id),
                    CampaignDraftRow.status == "draft",
                )
            )
        ).all()
        return len(rows)

    async def audit(self, session: AsyncSession, workspace_id: str) -> list[AuditEvent]:
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

    async def create_feedback(
        self,
        session: AsyncSession,
        workspace_id: str,
        actor_id: str,
        payload: FeedbackInput,
    ) -> FeedbackRecord:
        row = FeedbackEventRow(
            workspace_id=_uuid(workspace_id),
            actor_id=actor_id,
            target_type=payload.target_type,
            target_id=payload.target_id,
            rating=payload.rating,
            reason=payload.reason,
            notes=payload.notes,
        )
        session.add(row)
        await self.record(
            session,
            row.workspace_id,
            actor_id,
            "feedback_recorded",
            payload.target_type,
            payload.target_id,
            {"rating": payload.rating},
        )
        await session.commit()
        await session.refresh(row)
        return FeedbackRecord(
            id=str(row.id),
            workspace_id=str(row.workspace_id),
            actor_id=row.actor_id,
            target_type=row.target_type,  # type: ignore[arg-type]
            target_id=row.target_id,
            rating=row.rating,  # type: ignore[arg-type]
            reason=row.reason,
            notes=row.notes,
            created_at=row.created_at,
        )

    async def create_qa_evaluation(
        self,
        session: AsyncSession,
        workspace_id: str,
        evaluator_id: str,
        payload: QAEvaluationInput,
    ) -> QAEvaluationRecord:
        row = QAEvaluationRow(
            workspace_id=_uuid(workspace_id),
            research_run_id=_uuid(payload.research_run_id),
            account_id=_uuid(payload.account_id),
            evaluator_id=evaluator_id,
            company_validity=payload.company_validity,
            domain_correctness=payload.domain_correctness,
            icp_relevance=payload.icp_relevance,
            evidence_correctness=payload.evidence_correctness,
            signal_relevance=payload.signal_relevance,
            brief_usefulness=payload.brief_usefulness,
            evidence_links_working=payload.evidence_links_working,
            unsupported_important_claim=payload.unsupported_important_claim,
            notes=payload.notes,
        )
        session.add(row)
        await self.record(
            session,
            row.workspace_id,
            evaluator_id,
            "qa_evaluation_recorded",
            "account",
            payload.account_id,
            {"research_run_id": payload.research_run_id},
        )
        await session.commit()
        await session.refresh(row)
        return QAEvaluationRecord(
            id=str(row.id),
            workspace_id=str(row.workspace_id),
            evaluator_id=row.evaluator_id,
            research_run_id=str(row.research_run_id),
            account_id=str(row.account_id),
            company_validity=row.company_validity,  # type: ignore[arg-type]
            domain_correctness=row.domain_correctness,  # type: ignore[arg-type]
            icp_relevance=row.icp_relevance,
            evidence_correctness=row.evidence_correctness,  # type: ignore[arg-type]
            signal_relevance=row.signal_relevance,
            brief_usefulness=row.brief_usefulness,
            evidence_links_working=row.evidence_links_working,
            unsupported_important_claim=row.unsupported_important_claim,
            notes=row.notes,
            created_at=row.created_at,
        )

    @staticmethod
    def product_domain(row: ProductProfileRow) -> ProductProfile:
        raw_understanding = row.profile_data.get("understanding", [])
        understanding_items = (
            raw_understanding if isinstance(raw_understanding, list) else []
        )
        return ProductProfile(
            id=str(row.id),
            workspace_id=str(row.workspace_id),
            company_name=row.company_name,
            website=row.website,
            product=row.product,
            target_market=row.target_market,
            status=row.status,  # type: ignore[arg-type]
            understanding=[
                ProfileClaim.model_validate(item)
                for item in understanding_items
                if isinstance(item, dict)
            ],
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
            recommended=bool(definition.get("recommended")),
            qualification_logic=_string_list(definition.get("qualification_logic")),
            criteria_version=str(definition.get("criteria_version") or "legacy"),
            criteria=_criteria_list(definition.get("criteria")),
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
