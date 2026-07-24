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
    AccountOpportunityBrief,
    AuditEvent,
    CampaignDraft,
    CampaignUpdate,
    FeedbackInput,
    FeedbackRecord,
    ICP,
    ProductProfile,
    ProductProfileInput,
    ResearchRun,
    Workspace,
    WorkspaceCreate,
    utc_now,
)
from apps.api.app.config import settings
from apps.api.app.repositories.fixture import repository


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
    product_id: str, background_tasks: BackgroundTasks, principal: Current
) -> ResearchRun:
    try:
        run = repository.create_research(principal.workspace_id, product_id)
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
    if payload.action == "edit":
        if payload.subject is not None:
            campaign.subject = payload.subject
        if payload.body is not None:
            campaign.body = payload.body
        event = "campaign_draft_edited"
    elif payload.action == "approve":
        campaign.status = "approved"
        event = "campaign_draft_approved"
    else:
        campaign.status = "rejected"
        event = "campaign_draft_rejected"
    campaign.updated_at = datetime.now(campaign.updated_at.tzinfo)
    repository.record(
        principal.workspace_id, principal.user_id, event, "campaign", campaign.id
    )
    return campaign


def _csv_safe(value: object) -> str:
    text = str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


@router.get("/exports/accounts.csv")
def export_accounts(principal: Current) -> Response:
    approved = [
        b
        for b in repository.briefs.values()
        if b.account.workspace_id == principal.workspace_id
        and b.campaign.status == "approved"
    ]
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "company",
            "domain",
            "fit",
            "intent",
            "confidence",
            "priority",
            "top_signal",
            "recommended_action",
        ]
    )
    for brief in approved:
        account = brief.account
        writer.writerow(
            [
                _csv_safe(account.name),
                _csv_safe(account.domain),
                account.scores.fit.score,
                account.scores.intent.score,
                account.scores.confidence.score,
                account.scores.priority,
                _csv_safe(account.top_signal),
                _csv_safe(account.recommended_action),
            ]
        )
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
