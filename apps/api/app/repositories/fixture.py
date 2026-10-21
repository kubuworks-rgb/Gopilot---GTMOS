from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from apps.api.app.domain.models import (
    Account,
    AccountImportRecord,
    AccountImportSource,
    AccountOpportunityBrief,
    AuditEvent,
    CampaignDraft,
    ClaimStatus,
    Finding,
    ICP,
    ProductProfile,
    ProductMode,
    ResearchRun,
    Workspace,
)
from apps.api.app.repositories.demo_accounts import build_demo_accounts
from apps.api.app.services.scoring import score_account


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class FixtureRepository:
    """Deterministic local adapter. Never enabled in production."""

    def __init__(self) -> None:
        self._lock = RLock()
        self.workspaces: dict[str, Workspace] = {}
        self.memberships: dict[str, set[str]] = {}
        self.products: dict[str, ProductProfile] = {}
        self.runs: dict[str, ResearchRun] = {}
        self.icps: dict[str, ICP] = {}
        self.accounts: dict[str, Account] = {}
        self.briefs: dict[str, AccountOpportunityBrief] = {}
        self.audit: list[AuditEvent] = []
        self.demo_workspace_id = self.create_workspace("demo-user", "Kubu Works GTM").id
        profile = self.create_product(
            self.demo_workspace_id,
            "Kubu Works",
            "https://kubu.example",
            "Evidence-backed GTM intelligence platform",
            "Founder-led B2B SaaS companies in India",
        )
        run = self.create_research(self.demo_workspace_id, profile.id)
        self.complete_research(run.id)
        self.select_icp(self.demo_workspace_id, self.list_icps(self.demo_workspace_id)[0].id)

    def create_workspace(self, user_id: str, name: str) -> Workspace:
        workspace = Workspace(id=_id("ws"), name=name)
        self.workspaces[workspace.id] = workspace
        self.memberships.setdefault(user_id, set()).add(workspace.id)
        self.record(workspace.id, user_id, "workspace_created", "workspace", workspace.id)
        return workspace

    def assert_member(self, user_id: str, workspace_id: str) -> None:
        # The demo workspace admits any authenticated caller. This repository serves
        # the offline demo, where there is one workspace and no real tenancy to
        # protect -- and gating it on a hardcoded "demo-user" made the fixture
        # unusable with OIDC, since a real subject is never that string.
        # Live tenancy is enforced by the Postgres repository, which checks real
        # membership rows; see test_router_contract_parity.py for the boundary.
        if workspace_id == self.demo_workspace_id:
            self.memberships.setdefault(user_id, set()).add(workspace_id)
            return
        if workspace_id not in self.memberships.get(user_id, set()):
            raise PermissionError("Workspace membership required")

    def create_product(
        self, workspace_id: str, company: str, website: str, product: str, target: str
    ) -> ProductProfile:
        profile = ProductProfile(
            id=_id("prod"),
            workspace_id=workspace_id,
            company_name=company,
            website=website,
            product=product,
            target_market=target,
        )
        self.products[profile.id] = profile
        return profile

    def create_research(
        self,
        workspace_id: str,
        product_id: str,
        product_mode: ProductMode = ProductMode.BYOA_CORE,
    ) -> ResearchRun:
        if self.products.get(product_id, None) is None or self.products[product_id].workspace_id != workspace_id:
            raise KeyError("Product not found")
        run = ResearchRun(
            id=_id("run"), workspace_id=workspace_id, product_id=product_id,
            status="queued", current_stage="research_plan", product_mode=product_mode,
        )
        self.runs[run.id] = run
        return run

    def complete_research(self, run_id: str) -> None:
        with self._lock:
            run = self.runs[run_id]
            now = datetime.now(UTC)
            evidence_ids = [f"ev_{run_id[-4:]}_{index}" for index in range(1, 5)]
            run.status = "awaiting_icp"
            run.current_stage = "icp_selection"
            run.updated_at = now
            run.searches_used = 4
            run.documents_used = 4
            run.findings = [
                Finding(id=_id("finding"), category="market", claim="Small B2B teams need defensible account prioritisation before scaling outbound.", confidence=.92, status=ClaimStatus.SUPPORTED, evidence_ids=[evidence_ids[0]]),
                Finding(id=_id("finding"), category="competitor", claim="Most alternatives separate enrichment from evidence review.", confidence=.84, status=ClaimStatus.PARTIAL, evidence_ids=[evidence_ids[1]]),
                Finding(id=_id("finding"), category="pain_point", claim="Founder-led teams lose time reconciling scattered research and deciding who to approach.", confidence=.89, status=ClaimStatus.SUPPORTED, evidence_ids=[evidence_ids[2]]),
                Finding(id=_id("finding"), category="buying_trigger", claim="New GTM hiring and market expansion increase the value of repeatable account research.", confidence=.87, status=ClaimStatus.SUPPORTED, evidence_ids=[evidence_ids[3]]),
            ]
            if not any(item.research_run_id == run.id for item in self.icps.values()):
                self._create_icps(run, evidence_ids)

    def _create_icps(self, run: ResearchRun, evidence_ids: list[str]) -> None:
        candidates = [
            ("Founder-led India SaaS", "Indian B2B SaaS companies with 10-50 employees and founder-owned GTM.", ["B2B SaaS", "India", "10-50 employees"], ["Research scattered across tools", "No dedicated RevOps"], ["First GTM hires", "New segment launch"]),
            ("AI Services Scale-up", "Indian AI consultancies productising repeatable offers with small sales teams.", ["AI services", "India", "5-50 employees"], ["Inconsistent qualification", "Founder-dependent selling"], ["Product launch", "Sales hiring"]),
            ("Early Expansion SaaS", "APAC SaaS vendors entering India and building a local GTM motion.", ["B2B SaaS", "APAC", "20-100 employees"], ["Unfamiliar local market", "Low-signal target lists"], ["India expansion", "Partner hiring"]),
        ]
        for index, (name, description, firms, pains, triggers) in enumerate(candidates):
            icp = ICP(id=_id("icp"), workspace_id=run.workspace_id, research_run_id=run.id, name=name, description=description, firmographics=firms, pains=pains, triggers=triggers, rationale="Matches the confirmed product profile and evidence-backed buying context.", evidence_ids=[evidence_ids[index % len(evidence_ids)]])
            self.icps[icp.id] = icp

    def list_icps(self, workspace_id: str) -> list[ICP]:
        return [item for item in self.icps.values() if item.workspace_id == workspace_id]

    def select_icp(self, workspace_id: str, icp_id: str) -> ICP:
        selected = self.icps.get(icp_id)
        if selected is None or selected.workspace_id != workspace_id:
            raise KeyError("ICP not found")
        for item in self.icps.values():
            if item.workspace_id == workspace_id:
                item.selected = item.id == icp_id
        account_ids = [
            account_id
            for account_id, account in self.accounts.items()
            if account.workspace_id == workspace_id
        ]
        for account_id in account_ids:
            self.accounts.pop(account_id, None)
            self.briefs.pop(account_id, None)
        self._create_accounts(selected)
        run = self.runs[selected.research_run_id]
        run.status = "completed"
        run.current_stage = "completed"
        run.completed_at = datetime.now(UTC)
        return selected

    def _create_accounts(self, icp: ICP) -> None:
        for account, brief in build_demo_accounts(icp, datetime.now(UTC)):
            self.accounts[account.id] = account
            self.briefs[account.id] = brief

    def import_accounts(
        self,
        workspace_id: str,
        icp_id: str,
        records: list[AccountImportRecord],
        import_source: AccountImportSource,
    ) -> tuple[list[Account], list[str]]:
        icp = self.icps.get(icp_id)
        if icp is None or icp.workspace_id != workspace_id or not icp.selected:
            raise KeyError("Select an ICP before importing accounts")
        existing = {
            item.domain
            for item in self.accounts.values()
            if item.workspace_id == workspace_id
        }
        imported: list[Account] = []
        duplicates: list[str] = []
        now = datetime.now(UTC)
        for record in records:
            if record.domain in existing:
                duplicates.append(record.domain)
                continue
            scores = score_account(
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
            account = Account(
                id=_id("acct"),
                workspace_id=workspace_id,
                icp_id=icp_id,
                name=record.company_name,
                domain=record.domain,
                industry=record.industry or "Unverified",
                location=record.country or "Unverified",
                employee_band=record.employee_band or "Unverified",
                scores=scores,
                top_signal="No verified current signal",
                recommended_action="Research official sources before changing status.",
                last_researched_at=now,
                discovery_source=f"import:{import_source.value.lower()}",
                domain_validation="CANONICALIZED_UNVERIFIED",
                registrable_domain=record.domain,
                domain_confidence=0.55,
                priority_band="MONITOR",
                brief_state="RESEARCH_CANDIDATE",
                company_identity={
                    "canonical_company_name": record.company_name,
                    "canonical_registrable_domain": record.domain,
                    "verified_official_domains": [],
                    "identity_confidence": 0.55,
                    "unresolved_identity_warnings": [
                        "User-supplied domain has not yet been verified."
                    ],
                },
                product_mode=ProductMode.BYOA_CORE,
                import_source=import_source,
                provenance="IMPORTED",
                # Live mode keeps these; dropping them here made the demo ignore
                # columns the import form says it accepts.
                owner=record.owner,
                tags=list(record.tags),
            )
            campaign = CampaignDraft(
                id=_id("camp"),
                account_id=account.id,
                subject="",
                body="",
                status="draft",
                evidence_ids=[],
            )
            brief = AccountOpportunityBrief(
                account=account,
                why_it_fits=[],
                why_now=[],
                pain_hypotheses=[],
                recommended_problem="Official company evidence has not been collected yet.",
                recommended_offer="No outreach recommendation",
                recommended_action=account.recommended_action,
                risks=["Identity and ICP criteria remain unverified."],
                evidence=[],
                sources=[],
                signals=[],
                campaign=campaign,
                unknowns=[
                    "Official company identity",
                    "ICP fit",
                    "Current supported signal",
                ],
                brief_state="RESEARCH_CANDIDATE",
                verified_identity=account.company_identity,
                next_research_step="Fetch and verify the supplied official domain.",
            )
            self.accounts[account.id] = account
            self.briefs[account.id] = brief
            existing.add(record.domain)
            imported.append(account)
        return imported, sorted(set(duplicates))

    def record(self, workspace_id: str, actor_id: str, event: str, target_type: str, target_id: str, metadata: dict[str, str] | None = None) -> None:
        self.audit.append(AuditEvent(id=_id("audit"), workspace_id=workspace_id, actor_id=actor_id, event_type=event, target_type=target_type, target_id=target_id, metadata=metadata or {}))


repository = FixtureRepository()
