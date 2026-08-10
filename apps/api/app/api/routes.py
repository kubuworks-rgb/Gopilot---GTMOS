from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Response

from apps.api.app.api.dependencies import Principal, get_principal
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
    FeedbackInput,
    FeedbackRecord,
    ICP,
    ProductProfile,
    ProductProfileInput,
    ProductMode,
    ProductModeAvailability,
    ResearchRun,
    Workspace,
    WorkspaceCreate,
    ImportedAccountResult,
    utc_now,
)
from apps.api.app.config import settings
from apps.api.app.repositories.fixture import repository
from apps.api.app.services.byoa import (
    product_mode_availability,
    validate_account_import,
)
from apps.api.app.services.exports import EXPORT_COLUMNS, csv_safe, export_row
from apps.api.app.services.private_alpha import retention_policy


router = APIRouter(prefix="/api/v1")
Current = Annotated[Principal, Depends(get_principal)]


def _owned(item: object | None, principal: Principal) -> object:
    if item is None or getattr(item, "workspace_id", None) != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Resource not found")
    return item


@router.get("/bootstrap")
def bootstrap(principal: Current) -> dict[str, object]:
    workspace = repository.workspaces[principal.workspace_id]
    products = [
        p
        for p in repository.products.values()
        if p.workspace_id == principal.workspace_id
    ]
    runs = [
        r for r in repository.runs.values() if r.workspace_id == principal.workspace_id
    ]
    return {
        "mode": "fixture",
        "demo_data": True,
        # Same statement in both modes; a policy the user cannot read is not one.
        "retention": retention_policy(),
        "product_mode": (
            runs[-1].product_mode if runs else ProductMode.BYOA_CORE
        ),
        "mode_availability": product_mode_availability(),
        "provider_message": (
            "Account research is available. Automatic account discovery requires "
            "a configured search provider."
        ),
        "workspace": workspace,
        "product": products[-1] if products else None,
        "research_run": runs[-1] if runs else None,
        "icps": repository.list_icps(principal.workspace_id),
        "accounts": [
            a
            for a in repository.accounts.values()
            if a.workspace_id == principal.workspace_id
        ],
        "approval_count": sum(
            1
            for b in repository.briefs.values()
            if b.account.workspace_id == principal.workspace_id
            and b.campaign.status == "draft"
        ),
    }


@router.get("/product-modes", response_model=ProductModeAvailability)
def product_modes(principal: Current) -> ProductModeAvailability:
    del principal
    return product_mode_availability()


@router.post("/workspaces", response_model=Workspace, status_code=201)
def create_workspace(
    payload: WorkspaceCreate,
    x_demo_user: Annotated[str | None, Header()] = None,
) -> Workspace:
    if not settings.demo_auth_enabled:
        raise HTTPException(
            status_code=401,
            detail="Production workspace creation requires verified authentication",
        )
    return repository.create_workspace(x_demo_user or "demo-user", payload.name)


@router.post("/products", response_model=ProductProfile, status_code=201)
def create_product(payload: ProductProfileInput, principal: Current) -> ProductProfile:
    product = repository.create_product(
        principal.workspace_id,
        payload.company_name,
        payload.website,
        payload.product,
        payload.target_market,
    )
    repository.record(
        principal.workspace_id,
        principal.user_id,
        "product_confirmed",
        "product",
        product.id,
    )
    return product


@router.post("/research-runs", response_model=ResearchRun, status_code=202)
def create_research(
    product_id: str,
    background_tasks: BackgroundTasks,
    principal: Current,
    product_mode: ProductMode = ProductMode.BYOA_CORE,
) -> ResearchRun:
    availability = product_mode_availability()
    if (
        product_mode == ProductMode.AUTONOMOUS_DISCOVERY_EXPERIMENTAL
        and not availability.search_provider_configured
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CONFIGURATION_REQUIRED",
                "message": availability.message,
            },
        )
    try:
        run = repository.create_research(
            principal.workspace_id, product_id, product_mode
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    background_tasks.add_task(repository.complete_research, run.id)
    repository.record(
        principal.workspace_id,
        principal.user_id,
        "research_run_started",
        "research_run",
        run.id,
    )
    return run


@router.get("/research-runs/{run_id}", response_model=ResearchRun)
def get_research(run_id: str, principal: Current) -> ResearchRun:
    return _owned(repository.runs.get(run_id), principal)  # type: ignore[return-value]


@router.get("/icps", response_model=list[ICP])
def list_icps(principal: Current) -> list[ICP]:
    return repository.list_icps(principal.workspace_id)


@router.post("/icps/{icp_id}/select", response_model=ICP)
def select_icp(icp_id: str, principal: Current) -> ICP:
    try:
        item = repository.select_icp(principal.workspace_id, icp_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    repository.record(
        principal.workspace_id, principal.user_id, "icp_selected", "icp", icp_id
    )
    return item


@router.get("/accounts", response_model=list[Account])
def list_accounts(principal: Current, min_priority: int = 0) -> list[Account]:
    return sorted(
        [
            a
            for a in repository.accounts.values()
            if a.workspace_id == principal.workspace_id
            and a.scores.priority >= min_priority
        ],
        key=lambda item: item.scores.priority,
        reverse=True,
    )


@router.post(
    "/account-imports/validate",
    response_model=AccountImportValidation,
)
def validate_import(
    payload: AccountImportPayload,
    principal: Current,
) -> AccountImportValidation:
    del principal
    return validate_account_import(payload)


@router.post("/accounts/import", response_model=AccountImportResult, status_code=201)
def import_accounts(
    payload: AccountImportPayload,
    principal: Current,
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
    selected = next(
        (
            item
            for item in repository.list_icps(principal.workspace_id)
            if item.selected
        ),
        None,
    )
    if selected is None:
        raise HTTPException(status_code=409, detail="Select an ICP before importing")
    imported, existing_duplicates = repository.import_accounts(
        principal.workspace_id,
        selected.id,
        validation.accepted,
        validation.import_source,
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
                id=item.id,
                company_name=item.name,
                canonical_domain=item.domain,
                import_source=validation.import_source,
            )
            for item in imported
        ],
        issues=issues,
        duplicate_domains=sorted(
            set(validation.duplicate_domains) | set(existing_duplicates)
        ),
    )


@router.get(
    "/accounts/{account_id}/opportunity-brief", response_model=AccountOpportunityBrief
)
def get_brief(account_id: str, principal: Current) -> AccountOpportunityBrief:
    brief = repository.briefs.get(account_id)
    if brief is None or brief.account.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Account not found")
    repository.record(
        principal.workspace_id,
        principal.user_id,
        "opportunity_brief_viewed",
        "account",
        account_id,
    )
    return brief


@router.patch("/campaigns/{campaign_id}", response_model=CampaignDraft)
def update_campaign(
    campaign_id: str, payload: CampaignUpdate, principal: Current
) -> CampaignDraft:
    brief = next(
        (
            b
            for b in repository.briefs.values()
            if b.campaign.id == campaign_id
            and b.account.workspace_id == principal.workspace_id
        ),
        None,
    )
    if brief is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    campaign = brief.campaign
    if (
        payload.action in {"edit", "approve"}
        and brief.brief_state != "FOUNDER_READY"
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Outreach drafts are available only for evidence-gated "
                "FOUNDER_READY accounts"
            ),
        )
    if payload.action == "edit":
        if payload.subject is not None:
            campaign.subject = payload.subject
        if payload.body is not None:
            campaign.body = payload.body
        event = "campaign_draft_edited"
    elif payload.action == "approve":
        campaign.status = "approved"
        brief.account.review_status = AccountReviewStatus.APPROVED
        event = "campaign_draft_approved"
    else:
        campaign.status = "rejected"
        event = "campaign_draft_rejected"
    campaign.updated_at = datetime.now(campaign.updated_at.tzinfo)
    repository.record(
        principal.workspace_id, principal.user_id, event, "campaign", campaign.id
    )
    return campaign


@router.patch("/accounts/{account_id}/review", response_model=Account)
def review_account(
    account_id: str,
    payload: AccountReviewUpdate,
    principal: Current,
) -> Account:
    account = repository.accounts.get(account_id)
    if account is None or account.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Account not found")
    if (
        payload.brief_state == "FOUNDER_READY"
        and account.brief_state != "FOUNDER_READY"
    ):
        raise HTTPException(
            status_code=409,
            detail="FOUNDER_READY is evidence-gated and cannot be manually promoted",
        )
    account.review_status = payload.review_status
    if payload.brief_state is not None:
        account.brief_state = payload.brief_state
        brief = repository.briefs.get(account_id)
        if brief is not None:
            brief.brief_state = payload.brief_state
    repository.record(
        principal.workspace_id,
        principal.user_id,
        "account_review_updated",
        "account",
        account_id,
        {
            "review_status": payload.review_status.value,
            "brief_state": account.brief_state,
        },
    )
    return account


_csv_safe = csv_safe


@router.get("/exports/accounts.csv")
def export_accounts(principal: Current) -> Response:
    approved = [
        b
        for b in repository.briefs.values()
        if b.account.workspace_id == principal.workspace_id
        and b.account.review_status == AccountReviewStatus.APPROVED
    ]
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    # Shared with the live router so the two export surfaces cannot drift apart
    # again -- they already had, before this was consolidated.
    writer.writerow(EXPORT_COLUMNS)
    for brief in approved:
        account = brief.account
        writer.writerow(export_row(account, brief))
        repository.record(
            principal.workspace_id,
            principal.user_id,
            "account_exported",
            "account",
            account.id,
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=approved-accounts.csv"},
    )


@router.get("/audit", response_model=list[AuditEvent])
def audit(principal: Current) -> list[AuditEvent]:
    return [
        event
        for event in repository.audit
        if event.workspace_id == principal.workspace_id
    ]


@router.post("/feedback", response_model=FeedbackRecord, status_code=201)
def create_feedback(payload: FeedbackInput, principal: Current) -> FeedbackRecord:
    valid_target = False
    if payload.target_type == "account":
        account_target = repository.accounts.get(payload.target_id)
        valid_target = (
            account_target is not None
            and account_target.workspace_id == principal.workspace_id
        )
    elif payload.target_type == "brief":
        brief_target = repository.briefs.get(payload.target_id)
        valid_target = (
            brief_target is not None
            and brief_target.account.workspace_id == principal.workspace_id
        )
    elif payload.target_type == "signal":
        workspace_briefs = [
            item
            for item in repository.briefs.values()
            if item.account.workspace_id == principal.workspace_id
        ]
        valid_target = any(
            payload.target_id in [signal.id for signal in item.signals]
            for item in workspace_briefs
        )
    else:
        valid_target = any(
            payload.target_id in [finding.id for finding in run.findings]
            for run in repository.runs.values()
            if run.workspace_id == principal.workspace_id
        )
    if not valid_target:
        raise HTTPException(status_code=404, detail="Feedback target not found")
    repository.record(
        principal.workspace_id,
        principal.user_id,
        "feedback_recorded",
        payload.target_type,
        payload.target_id,
        {"rating": payload.rating},
    )
    return FeedbackRecord(
        id=str(uuid4()),
        workspace_id=principal.workspace_id,
        actor_id=principal.user_id,
        **payload.model_dump(),
        created_at=utc_now(),
    )
