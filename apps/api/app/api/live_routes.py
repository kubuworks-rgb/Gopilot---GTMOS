from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import HttpUrl
from redis.exceptions import RedisError
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.config import settings
from apps.api.app.db.models import (
    AccountRow,
    ApprovalRequestRow,
    EvidenceFactRow,
    GTMFindingRow,
    ICPProfileRow,
    IntentSignalRow,
    OpportunityBriefRow,
    ResearchRunRow,
    SourceChunkRow,
    SourceDocumentRow,
)
from apps.api.app.db.session import get_session
from apps.api.app.domain.models import (
    Account,
    AccountImportIssue,
    AccountImportPayload,
    AccountImportResult,
    AccountImportValidation,
    AccountReviewStatus,
    AccountReviewUpdate,
    AccountOpportunityBrief,
    AuditEvent,
    CampaignDraft,
    CampaignUpdate,
    ClaimStatus,
    EvidenceFact,
    FeedbackInput,
    FeedbackRecord,
    ICP,
    ProductProfile,
    ProductProfileInput,
    ProductMode,
    ProductModeAvailability,
    QAEvaluationInput,
    QAEvaluationRecord,
    ResearchEvidence,
    ResearchRun,
    SourceChunk,
    SourceDocument,
    Workspace,
    WorkspaceCreate,
    ImportedAccountResult,
)
from apps.api.app.jobs.queue import ResearchJob, enqueue_job
from apps.api.app.providers.live import GatewayProviderError, LiveResearchProvider
from apps.api.app.repositories.postgres import repository
from apps.api.app.security.tokens import AuthError, verify_bearer_token
from apps.api.app.services.private_alpha import (
    AccessDenied,
    LimitExceeded,
    assert_daily_import_quota,
    assert_export_size,
    assert_import_size,
    assert_invited,
    assert_run_concurrency,
    assert_workspace_capacity,
    assert_workspace_quota,
    experimental_discovery_allowed,
)
from apps.api.app.services.byoa import (
    product_mode_availability,
    validate_account_import,
)
from apps.api.app.services.exports import EXPORT_COLUMNS, csv_safe, export_row


router = APIRouter(prefix="/api/v1")
Database = Annotated[AsyncSession, Depends(get_session)]


@dataclass(frozen=True)
class LivePrincipal:
    user_id: str
    workspace_id: str
    role: str


async def authenticated_user_id(
    authorization: str | None, x_demo_user: str | None
) -> str:
    """Resolve the caller's identity, failing closed.

    In `oidc` mode the identity comes only from a verified token signature. The demo
    header is never consulted, so it cannot be used to impersonate anyone.
    """

    if settings.auth_mode == "oidc":
        try:
            verified = await verify_bearer_token(authorization)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        email = verified.claims.get("email")
        try:
            assert_invited(verified.subject, str(email) if email else None)
        except AccessDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return verified.subject
    if not settings.demo_auth_enabled:
        raise HTTPException(
            status_code=401,
            detail="Verified authentication is required when demo auth is disabled",
        )
    user_id = x_demo_user or "demo-user"
    try:
        assert_invited(user_id)
    except AccessDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return user_id


async def get_live_principal(
    session: Database,
    authorization: Annotated[str | None, Header()] = None,
    x_demo_user: Annotated[str | None, Header()] = None,
    x_workspace_id: Annotated[str | None, Header()] = None,
) -> LivePrincipal:
    user_id = await authenticated_user_id(authorization, x_demo_user)
    try:
        membership = await repository.resolve_membership(
            session, user_id, x_workspace_id
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=403, detail="Workspace membership required"
        ) from exc
    if membership is None:
        raise HTTPException(
            status_code=404,
            detail="No workspace exists for this user; create one first",
        )
    return LivePrincipal(
        user_id=user_id,
        workspace_id=str(membership.workspace_id),
        role=membership.role,
    )


Current = Annotated[LivePrincipal, Depends(get_live_principal)]


def _optional_positive_int(value: object) -> int | None:
    if isinstance(value, int):
        return value or None
    if isinstance(value, str) and value.isdigit():
        return int(value) or None
    return None


@router.get("/bootstrap")
async def bootstrap(principal: Current, session: Database) -> dict[str, object]:
    workspace = await repository.workspace(session, principal.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    product_row = await repository.latest_product(session, principal.workspace_id)
    run_row = await repository.latest_run(session, principal.workspace_id)
    try:
        capabilities = [
            item.model_dump(mode="json")
            for item in await LiveResearchProvider().capabilities()
        ]
    except GatewayProviderError as exc:
        capabilities = [
            {
                "channel": "research-gateway",
                "status": "unavailable",
                "detail": exc.safe_message,
            }
        ]
    availability = product_mode_availability()
    run_domain = (
        await repository.run_domain(session, run_row) if run_row is not None else None
    )
    return {
        "mode": "live",
        "demo_data": False,
        "product_mode": (
            run_domain.product_mode if run_domain is not None else ProductMode.BYOA_CORE
        ),
        "mode_availability": availability,
        "provider_message": availability.message,
        "workspace": workspace,
        "product": (
            repository.product_domain(product_row) if product_row is not None else None
        ),
        "research_run": run_domain,
        "icps": await repository.list_icps(session, principal.workspace_id),
        "accounts": await repository.list_accounts(session, principal.workspace_id),
        "approval_count": await repository.approval_count(
            session, principal.workspace_id
        ),
        "capabilities": capabilities,
    }


@router.get("/product-modes", response_model=ProductModeAvailability)
async def product_modes(principal: Current) -> ProductModeAvailability:
    del principal
    return product_mode_availability()


@router.post("/workspaces", response_model=Workspace, status_code=201)
async def create_workspace(
    payload: WorkspaceCreate,
    session: Database,
    authorization: Annotated[str | None, Header()] = None,
    x_demo_user: Annotated[str | None, Header()] = None,
) -> Workspace:
    # Workspace creation predates membership, so it authenticates the caller without
    # resolving one — but it must still authenticate.
    user_id = await authenticated_user_id(authorization, x_demo_user)
    try:
        await assert_workspace_quota(session, user_id)
    except LimitExceeded as exc:
        raise HTTPException(status_code=429, detail=exc.as_detail()) from exc
    return await repository.create_workspace(session, user_id, payload.name)


@router.post("/products", response_model=ProductProfile, status_code=201)
async def create_product(
    payload: ProductProfileInput, principal: Current, session: Database
) -> ProductProfile:
    return await repository.create_product(
        session,
        principal.workspace_id,
        principal.user_id,
        company_name=payload.company_name,
        website=payload.website,
        product=payload.product,
        target_market=payload.target_market,
    )


async def _enqueue_or_fail(
    session: AsyncSession, run: ResearchRunRow, job: ResearchJob
) -> None:
    try:
        await enqueue_job(job)
    except RedisError as exc:
        run.status = "failed"
        run.current_stage = "queue_failed"
        run.error = {
            "category": "QUEUE_UNAVAILABLE",
            "message": "Redis job queue is unavailable",
            "retryable": True,
        }
        run.updated_at = datetime.now(UTC)
        await session.commit()
        raise HTTPException(
            status_code=503, detail="Research queue is unavailable"
        ) from exc


@router.post("/research-runs", response_model=ResearchRun, status_code=202)
async def create_research(
    product_id: str,
    principal: Current,
    session: Database,
    product_mode: ProductMode = ProductMode.BYOA_CORE,
) -> ResearchRun:
    availability = product_mode_availability()
    if product_mode == ProductMode.AUTONOMOUS_DISCOVERY_EXPERIMENTAL:
        if not experimental_discovery_allowed():
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "EXPERIMENTAL_DISCOVERY_DISABLED",
                    "message": (
                        "Automatic discovery is disabled during the private alpha. "
                        "Account research remains available."
                    ),
                },
            )
        if not availability.search_provider_configured:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "CONFIGURATION_REQUIRED",
                    "message": availability.message,
                },
            )
    try:
        await assert_run_concurrency(session, principal.workspace_id)
    except LimitExceeded as exc:
        raise HTTPException(status_code=429, detail=exc.as_detail()) from exc
    try:
        result = await repository.create_run(
            session,
            principal.workspace_id,
            principal.user_id,
            product_id,
            {
                "max_searches": settings.max_research_searches,
                "max_documents": settings.max_research_documents,
                "max_elapsed_seconds": settings.max_elapsed_seconds,
            },
            product_mode=product_mode,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    run = await repository.run_row(session, result.id, principal.workspace_id)
    if run is None:
        raise HTTPException(status_code=500, detail="Research run was not persisted")
    if product_mode == ProductMode.BYOA_CORE:
        await repository.initialize_byoa_run(
            session,
            result.id,
            principal.workspace_id,
            principal.user_id,
        )
        refreshed = await repository.run_row(session, result.id, principal.workspace_id)
        if refreshed is None:
            raise HTTPException(status_code=500, detail="BYOA run was not persisted")
        return await repository.run_domain(session, refreshed)
    await _enqueue_or_fail(
        session,
        run,
        ResearchJob(
            kind="research",
            workspace_id=principal.workspace_id,
            target_id=result.id,
            actor_id=principal.user_id,
        ),
    )
    return result


@router.get("/research-runs/{run_id}", response_model=ResearchRun)
async def get_research(
    run_id: str, principal: Current, session: Database
) -> ResearchRun:
    try:
        row = await repository.run_row(session, run_id, principal.workspace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Research run not found") from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Research run not found")
    return await repository.run_domain(session, row)


@router.get(
    "/research-runs/{run_id}/evidence",
    response_model=ResearchEvidence,
)
async def get_research_evidence(
    run_id: str, principal: Current, session: Database
) -> ResearchEvidence:
    row = await repository.run_row(session, run_id, principal.workspace_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Research run not found")
    sources = list(
        (
            await session.scalars(
                select(SourceDocumentRow)
                .where(
                    SourceDocumentRow.research_run_id == row.id,
                    SourceDocumentRow.workspace_id == uuid.UUID(principal.workspace_id),
                )
                .order_by(SourceDocumentRow.created_at)
            )
        ).all()
    )
    source_ids = [source.id for source in sources]
    evidence_rows = (
        list(
            (
                await session.scalars(
                    select(EvidenceFactRow)
                    .where(
                        EvidenceFactRow.workspace_id
                        == uuid.UUID(principal.workspace_id),
                        EvidenceFactRow.source_id.in_(source_ids),
                    )
                    .order_by(EvidenceFactRow.created_at)
                )
            ).all()
        )
        if source_ids
        else []
    )
    chunks = (
        list(
            (
                await session.scalars(
                    select(SourceChunkRow)
                    .where(
                        SourceChunkRow.workspace_id
                        == uuid.UUID(principal.workspace_id),
                        SourceChunkRow.source_document_id.in_(source_ids),
                    )
                    .order_by(
                        SourceChunkRow.source_document_id,
                        SourceChunkRow.ordinal,
                    )
                )
            ).all()
        )
        if source_ids
        else []
    )
    chunk_by_evidence = {
        evidence.id: next(
            (
                chunk.id
                for chunk in chunks
                if chunk.source_document_id == evidence.source_id
                and evidence.passage in chunk.text
            ),
            None,
        )
        for evidence in evidence_rows
    }
    run_domain = await repository.run_domain(session, row)
    return ResearchEvidence(
        run_id=str(row.id),
        findings=run_domain.findings,
        evidence=[
            EvidenceFact(
                id=str(item.id),
                workspace_id=str(item.workspace_id),
                source_id=str(item.source_id),
                passage=item.passage,
                claim=item.claim,
                confidence=float(item.confidence),
                status=ClaimStatus(item.status),
                observed_at=item.observed_at,
                source_chunk_id=(
                    str(chunk_by_evidence[item.id])
                    if chunk_by_evidence[item.id] is not None
                    else None
                ),
            )
            for item in evidence_rows
        ],
        sources=[
            SourceDocument(
                id=str(item.id),
                workspace_id=str(item.workspace_id),
                platform=item.platform,
                source_type=item.source_type,
                backend=item.backend,
                url=HttpUrl(item.url),
                canonical_url=HttpUrl(item.canonical_url),
                title=item.title,
                published_at=item.published_at,
                retrieved_at=item.retrieved_at,
                permission_classification=item.permission_classification,
                trust_score=item.trust_score,
                demo_data=False,
                content_hash=item.content_hash,
                content_type=str(item.source_metadata.get("content_type") or "")
                or None,
                normalized_text_length=_optional_positive_int(
                    item.source_metadata.get("normalized_text_length")
                ),
            )
            for item in sources
        ],
        chunks=[
            SourceChunk(
                id=str(item.id),
                source_document_id=str(item.source_document_id),
                ordinal=item.ordinal,
                text=item.text,
                content_hash=item.content_hash,
            )
            for item in chunks
        ],
    )


@router.get("/icps", response_model=list[ICP])
async def list_icps(principal: Current, session: Database) -> list[ICP]:
    return await repository.list_icps(session, principal.workspace_id)


@router.post("/icps/{icp_id}/select", response_model=ICP, status_code=202)
async def select_icp(icp_id: str, principal: Current, session: Database) -> ICP:
    try:
        selected = await repository.select_icp(
            session, principal.workspace_id, principal.user_id, icp_id
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ICP not found") from exc
    run = await repository.run_row(
        session, selected.research_run_id, principal.workspace_id
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found")
    mode = ProductMode(
        str(run.budgets.get("product_mode") or ProductMode.BYOA_CORE.value)
    )
    if mode == ProductMode.BYOA_CORE:
        return selected
    if not experimental_discovery_allowed():
        raise HTTPException(
            status_code=409,
            detail={
                "code": "EXPERIMENTAL_DISCOVERY_DISABLED",
                "message": (
                    "Automatic discovery is disabled during the private alpha."
                ),
            },
        )
    availability = product_mode_availability()
    if not availability.search_provider_configured:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CONFIGURATION_REQUIRED",
                "message": availability.message,
            },
        )
    await _enqueue_or_fail(
        session,
        run,
        ResearchJob(
            kind="discover_accounts",
            workspace_id=principal.workspace_id,
            target_id=selected.id,
            actor_id=principal.user_id,
        ),
    )
    return selected


@router.post("/accounts/refresh", status_code=202)
async def refresh_accounts(principal: Current, session: Database) -> dict[str, str]:
    if not experimental_discovery_allowed():
        raise HTTPException(
            status_code=409,
            detail={
                "code": "EXPERIMENTAL_DISCOVERY_DISABLED",
                "message": "Automatic discovery is disabled during the private alpha.",
            },
        )
    availability = product_mode_availability()
    if not availability.search_provider_configured:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CONFIGURATION_REQUIRED",
                "message": availability.message,
            },
        )
    icp = await session.scalar(
        select(ICPProfileRow)
        .where(
            ICPProfileRow.workspace_id == uuid.UUID(principal.workspace_id),
            ICPProfileRow.selected_at.is_not(None),
        )
        .order_by(desc(ICPProfileRow.selected_at))
        .limit(1)
    )
    if icp is None:
        raise HTTPException(status_code=409, detail="Select an ICP first")
    run = await repository.run_row(
        session, str(icp.research_run_id), principal.workspace_id
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found")
    await _enqueue_or_fail(
        session,
        run,
        ResearchJob(
            kind="discover_accounts",
            workspace_id=principal.workspace_id,
            target_id=str(icp.id),
            actor_id=principal.user_id,
        ),
    )
    return {"status": "queued", "job": "discover_accounts"}


@router.post(
    "/account-imports/validate",
    response_model=AccountImportValidation,
)
async def validate_import(
    payload: AccountImportPayload,
    principal: Current,
) -> AccountImportValidation:
    del principal
    return validate_account_import(payload)


@router.post("/accounts/import", response_model=AccountImportResult, status_code=201)
async def import_accounts(
    payload: AccountImportPayload,
    principal: Current,
    session: Database,
) -> AccountImportResult:
    validation = validate_account_import(payload)
    if not validation.accepted:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "NO_VALID_ACCOUNTS",
                "issues": [item.model_dump() for item in validation.issues],
            },
        )
    # Checked before anything is written, so a refused import leaves no partial state.
    try:
        assert_import_size(len(validation.accepted))
        await assert_daily_import_quota(session, principal.workspace_id)
        await assert_workspace_capacity(
            session, principal.workspace_id, len(validation.accepted)
        )
    except LimitExceeded as exc:
        raise HTTPException(status_code=429, detail=exc.as_detail()) from exc
    icp = await session.scalar(
        select(ICPProfileRow)
        .where(
            ICPProfileRow.workspace_id == uuid.UUID(principal.workspace_id),
            ICPProfileRow.selected_at.is_not(None),
        )
        .order_by(desc(ICPProfileRow.selected_at))
        .limit(1)
    )
    if icp is None:
        raise HTTPException(
            status_code=409,
            detail="Start a BYOA run or select an ICP before importing accounts",
        )
    imported_rows, existing_duplicates = await repository.import_accounts(
        session,
        workspace_id=principal.workspace_id,
        actor_id=principal.user_id,
        icp_id=str(icp.id),
        records=validation.accepted,
        import_source=validation.import_source,
    )
    duplicate_domains = sorted(
        set(validation.duplicate_domains) | set(existing_duplicates)
    )
    issues = list(validation.issues)
    issues.extend(
        AccountImportIssue(
            row=0,
            field="domain",
            code="WORKSPACE_DUPLICATE",
            message=f"{domain} already exists in this workspace",
        )
        for domain in existing_duplicates
    )
    return AccountImportResult(
        imported=[
            ImportedAccountResult(
                id=str(row.id),
                company_name=row.name,
                canonical_domain=row.domain,
                import_source=validation.import_source,
            )
            for row in imported_rows
        ],
        issues=issues,
        duplicate_domains=duplicate_domains,
    )


@router.post("/accounts/{account_id}/research", status_code=202)
async def research_account(
    account_id: str, principal: Current, session: Database
) -> dict[str, str]:
    accounts = await repository.list_accounts(session, principal.workspace_id)
    if not any(item.id == account_id for item in accounts):
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        await enqueue_job(
            ResearchJob(
                kind="research_account",
                workspace_id=principal.workspace_id,
                target_id=account_id,
                actor_id=principal.user_id,
            )
        )
    except RedisError as exc:
        raise HTTPException(
            status_code=503, detail="Research queue is unavailable"
        ) from exc
    return {"status": "queued", "job": "research_account"}


@router.patch("/accounts/{account_id}/review", response_model=Account)
async def review_account(
    account_id: str,
    payload: AccountReviewUpdate,
    principal: Current,
    session: Database,
) -> Account:
    try:
        account_uuid = uuid.UUID(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Account not found") from exc
    row = await session.get(AccountRow, account_uuid)
    if row is None or str(row.workspace_id) != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Account not found")
    current_state = str(row.attributes.get("brief_state") or "RESEARCH_CANDIDATE")
    if payload.brief_state == "FOUNDER_READY" and current_state != "FOUNDER_READY":
        raise HTTPException(
            status_code=409,
            detail="FOUNDER_READY is evidence-gated and cannot be manually promoted",
        )
    row.attributes = {
        **row.attributes,
        "review_status": payload.review_status.value,
        "brief_state": payload.brief_state or current_state,
    }
    await repository.record(
        session,
        row.workspace_id,
        principal.user_id,
        "account_review_updated",
        "account",
        account_id,
        {
            "review_status": payload.review_status.value,
            "brief_state": str(payload.brief_state or current_state),
        },
    )
    await session.commit()
    account = await repository.account_domain(session, row)
    if account is None:
        raise HTTPException(status_code=409, detail="Account is not ready for review")
    return account


@router.post("/accounts/{account_id}/regenerate-brief", status_code=202)
async def regenerate_brief(
    account_id: str, principal: Current, session: Database
) -> dict[str, str]:
    accounts = await repository.list_accounts(session, principal.workspace_id)
    if not any(item.id == account_id for item in accounts):
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        await enqueue_job(
            ResearchJob(
                kind="regenerate_brief",
                workspace_id=principal.workspace_id,
                target_id=account_id,
                actor_id=principal.user_id,
            )
        )
    except RedisError as exc:
        raise HTTPException(
            status_code=503, detail="Research queue is unavailable"
        ) from exc
    return {"status": "queued", "job": "regenerate_brief"}


@router.get("/accounts", response_model=list[Account])
async def list_accounts(
    principal: Current, session: Database, min_priority: int = 0
) -> list[Account]:
    return [
        item
        for item in await repository.list_accounts(session, principal.workspace_id)
        if item.scores.priority >= min_priority
    ]


@router.get(
    "/accounts/{account_id}/opportunity-brief",
    response_model=AccountOpportunityBrief,
)
async def get_brief(
    account_id: str, principal: Current, session: Database
) -> AccountOpportunityBrief:
    try:
        brief = await repository.brief(session, principal.workspace_id, account_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Account not found") from exc
    if brief is None:
        raise HTTPException(status_code=404, detail="Account brief not found")
    await repository.record(
        session,
        uuid.UUID(principal.workspace_id),
        principal.user_id,
        "opportunity_brief_viewed",
        "account",
        account_id,
    )
    await session.commit()
    return brief


@router.patch("/campaigns/{campaign_id}", response_model=CampaignDraft)
async def update_campaign(
    campaign_id: str,
    payload: CampaignUpdate,
    principal: Current,
    session: Database,
) -> CampaignDraft:
    try:
        campaign = await repository.campaign(
            session, principal.workspace_id, campaign_id
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Campaign not found") from exc
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    account = await session.get(AccountRow, campaign.account_id)
    brief_state = (
        str(account.attributes.get("brief_state") or "RESEARCH_CANDIDATE")
        if account is not None
        else "RESEARCH_CANDIDATE"
    )
    if payload.action in {"edit", "approve"} and brief_state != "FOUNDER_READY":
        raise HTTPException(
            status_code=409,
            detail=(
                "Outreach drafts are available only for evidence-gated "
                "FOUNDER_READY accounts"
            ),
        )
    if payload.action == "edit":
        campaign.subject = (
            payload.subject if payload.subject is not None else campaign.subject
        )
        campaign.body = payload.body if payload.body is not None else campaign.body
        event = "campaign_draft_edited"
    elif payload.action == "approve":
        campaign.status = "approved"
        event = "campaign_draft_approved"
    else:
        campaign.status = "rejected"
        event = "campaign_draft_rejected"
    campaign.updated_at = datetime.now(UTC)
    approval = await session.scalar(
        select(ApprovalRequestRow)
        .where(ApprovalRequestRow.campaign_draft_id == campaign.id)
        .order_by(desc(ApprovalRequestRow.created_at))
        .limit(1)
    )
    if approval is not None and payload.action in {"approve", "reject"}:
        approval.status = "approved" if payload.action == "approve" else "rejected"
        approval.decided_by = principal.user_id
        approval.decided_at = datetime.now(UTC)
    await repository.record(
        session,
        campaign.workspace_id,
        principal.user_id,
        event,
        "campaign",
        campaign_id,
    )
    await session.commit()
    return CampaignDraft(
        id=str(campaign.id),
        account_id=str(campaign.account_id),
        subject=campaign.subject,
        body=campaign.body,
        status=campaign.status,  # type: ignore[arg-type]
        evidence_ids=campaign.evidence_ids,
        updated_at=campaign.updated_at,
    )


_csv_safe = csv_safe


@router.get("/exports/accounts.csv")
async def export_accounts(principal: Current, session: Database) -> Response:
    accounts = [
        item
        for item in await repository.list_accounts(session, principal.workspace_id)
        if item.review_status == AccountReviewStatus.APPROVED
    ]
    try:
        assert_export_size(len(accounts))
    except LimitExceeded as exc:
        raise HTTPException(status_code=429, detail=exc.as_detail()) from exc
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(EXPORT_COLUMNS)
    for account in accounts:
        brief = await repository.brief(
            session, principal.workspace_id, account.id
        )
        writer.writerow(export_row(account, brief))
        await repository.record(
            session,
            uuid.UUID(principal.workspace_id),
            principal.user_id,
            "account_exported",
            "account",
            account.id,
        )
    await session.commit()
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=approved-accounts.csv"},
    )


@router.get("/audit", response_model=list[AuditEvent])
async def audit(principal: Current, session: Database) -> list[AuditEvent]:
    return await repository.audit(session, principal.workspace_id)


@router.post("/feedback", response_model=FeedbackRecord, status_code=201)
async def create_feedback(
    payload: FeedbackInput, principal: Current, session: Database
) -> FeedbackRecord:
    model_by_target = {
        "account": AccountRow,
        "signal": IntentSignalRow,
        "finding": GTMFindingRow,
        "brief": OpportunityBriefRow,
    }
    try:
        target_uuid = uuid.UUID(payload.target_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404, detail="Feedback target not found"
        ) from exc
    target = await session.get(model_by_target[payload.target_type], target_uuid)
    if target is None or str(target.workspace_id) != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Feedback target not found")
    return await repository.create_feedback(
        session,
        principal.workspace_id,
        principal.user_id,
        payload,
    )


@router.post("/qa-evaluations", response_model=QAEvaluationRecord, status_code=201)
async def create_qa_evaluation(
    payload: QAEvaluationInput, principal: Current, session: Database
) -> QAEvaluationRecord:
    try:
        account_id = uuid.UUID(payload.account_id)
        run_id = uuid.UUID(payload.research_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="QA target not found") from exc
    account = await session.get(AccountRow, account_id)
    run = await session.get(ResearchRunRow, run_id)
    if (
        account is None
        or run is None
        or str(account.workspace_id) != principal.workspace_id
        or str(run.workspace_id) != principal.workspace_id
    ):
        raise HTTPException(status_code=404, detail="QA target not found")
    return await repository.create_qa_evaluation(
        session,
        principal.workspace_id,
        principal.user_id,
        payload,
    )
