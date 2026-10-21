"""The made-up accounts behind the offline demo.

Every company here is invented and lives on a reserved `.example` or `.test`
domain, so nothing in the demo can be mistaken for a real business or resolve to
one. Every source is marked `demo_data=True`, which the UI renders as DEMO DATA.

The data is made up; the machinery is not. Scores come from the real
`score_account`, bands from the real `priority_band`, and the rejected evidence
on Quillfront is produced by running the real entity-safety gate on a lookalike
passage. The six accounts are chosen so that one click through the demo shows
each outcome the product can reach:

- NovaLedger, SignalForge AI, CloudKite: verified fit and a dated signal, ready
  for a human-approved draft. CloudKite was found by ICP discovery; the rest
  were brought by the user.
- Brightwave Analytics: a strong signal, but part of the site failed to load, so
  fit stays "Not determined" instead of being guessed.
- Harbor Ledger: a good fit with no current event. Monitor, don't message.
- Quillfront: a funding headline from a lookalike domain, held back rather than
  attached to the wrong company.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal, cast
from uuid import uuid4

from entity_safety import (
    SOURCE_ROLE_FIRST_PARTY,
    CompanyIdentityRecord,
    EntityRelation,
    VerifiedEntityRelationship,
    assess_evidence_attachment,
)
from pydantic import HttpUrl

from apps.api.app.domain.models import (
    Account,
    AccountImportSource,
    AccountOpportunityBrief,
    CampaignDraft,
    ClaimStatus,
    CompanySizeStatus,
    EvidenceClaim,
    EvidenceFact,
    ICP,
    QualificationStatus,
    RetrievalAttempt,
    RetrievalOutcome,
    RetrievalSummary,
    Signal,
    SourceDocument,
)
from apps.api.app.services.scoring import priority_band, score_account, signal_decay


BriefState = Literal["FOUNDER_READY", "RESEARCH_CANDIDATE", "MONITOR", "IDENTITY_REVIEW_REQUIRED"]
PriorityBand = Literal["HIGH", "MEDIUM", "LOW", "MONITOR"]


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


@dataclass(frozen=True)
class _Page:
    path: str
    title: str
    passage: str
    claim: str
    kind: str = "fact"  # "fact" (company fact) or "signal" (dated event)


@dataclass(frozen=True)
class _Spec:
    name: str
    domain: str
    industry: str | None
    location: str | None
    employee_band: str | None
    industry_match: float | None
    size_match: float | None
    geography_match: float | None
    pages: tuple[_Page, ...]
    attempts: tuple[tuple[str, RetrievalOutcome, str | None], ...]
    import_source: AccountImportSource | None  # None: found by ICP discovery
    brief_state: BriefState
    qualification: QualificationStatus
    owner: str | None = None
    tags: tuple[str, ...] = ()
    signal_type: str | None = None
    signal_strength: float = 0
    signal_age_days: int = 0
    icp_facts: tuple[str, ...] = ()
    icp_mismatches: tuple[str, ...] = ()
    icp_unknowns: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    hypotheses: tuple[str, ...] = ()
    summary: str = ""
    recommended_problem: str = ""
    recommended_offer: str = "No outreach recommendation"
    recommended_action: str = ""
    next_research_step: str | None = None
    reason_not_to_target: str | None = None
    risks: tuple[str, ...] = ()
    lookalikes: tuple[tuple[str, str, str], ...] = field(default=())


_DEMO_RISK = "DEMO DATA: an invented company on a reserved domain. Run live research before using anything here."

SPECS: tuple[_Spec, ...] = (
    _Spec(
        name="NovaLedger",
        domain="novaledger.example",
        industry="B2B SaaS",
        location="Bengaluru, India",
        employee_band="21-50",
        industry_match=94,
        size_match=90,
        geography_match=100,
        pages=(
            _Page("/", "NovaLedger - accounts payable automation", "NovaLedger is a B2B SaaS platform that automates accounts payable for mid-sized finance teams.", "NovaLedger sells B2B SaaS for finance teams."),
            _Page("/about", "About NovaLedger", "NovaLedger is headquartered in Bengaluru, India, and has a team of 38 people across engineering, sales and support.", "NovaLedger is based in Bengaluru with a 38-person team."),
            _Page("/careers", "Careers at NovaLedger", "We are hiring two account executives and a revenue operations lead to build our first outbound sales team.", "NovaLedger opened three go-to-market roles this month.", "signal"),
        ),
        attempts=(("/", RetrievalOutcome.RETRIEVED, None), ("/about", RetrievalOutcome.RETRIEVED, None), ("/careers", RetrievalOutcome.RETRIEVED, None), ("/customers", RetrievalOutcome.NOT_FOUND, "No customers page on this site.")),
        import_source=AccountImportSource.CSV_UPLOAD,
        brief_state="FOUNDER_READY",
        qualification=QualificationStatus.QUALIFIED,
        owner="Asha",
        tags=("q4-pilot",),
        signal_type="hiring",
        signal_strength=86,
        signal_age_days=8,
        icp_facts=("Industry: B2B SaaS, as the ICP requires.", "Location: Bengaluru, India, inside the target market.", "Team size: 38 people, inside the 10-50 range."),
        hypotheses=("Building a first outbound team usually means the founder still decides who to target, and may want that research to be repeatable.",),
        summary="NovaLedger fits the ICP on every criterion and opened three sales roles eight days ago.",
        recommended_problem="The first sales hires need a target list they can trust and explain.",
        recommended_offer="A human-reviewed account research pilot for their first outbound segment.",
        recommended_action="Review the draft below and send it yourself if it reads right.",
        next_research_step="Check whether the sales roles are filled before the pilot starts.",
        risks=("The hiring signal shows intent to build a team, not a budget decision.",),
    ),
    _Spec(
        name="SignalForge AI",
        domain="signalforge.example",
        industry="AI SaaS",
        location="Pune, India",
        employee_band="11-20",
        industry_match=91,
        size_match=96,
        geography_match=100,
        pages=(
            _Page("/", "SignalForge AI - anomaly detection for operations teams", "SignalForge AI is enterprise software that detects anomalies in operational data for logistics companies.", "SignalForge AI sells enterprise software to logistics companies."),
            _Page("/about", "About SignalForge AI", "SignalForge AI is based in Pune, India. We are a team of 16 people.", "SignalForge AI is based in Pune with a 16-person team."),
            _Page("/blog/enterprise-tier", "Introducing SignalForge Enterprise", "Today we launched SignalForge Enterprise, a new tier with single sign-on, audit logs and a dedicated success manager.", "SignalForge AI launched an enterprise tier.", "signal"),
        ),
        attempts=(("/", RetrievalOutcome.RETRIEVED, None), ("/about", RetrievalOutcome.RETRIEVED, None), ("/blog/enterprise-tier", RetrievalOutcome.RETRIEVED, None), ("/careers", RetrievalOutcome.NOT_FOUND, "No careers page on this site.")),
        import_source=AccountImportSource.CSV_UPLOAD,
        brief_state="FOUNDER_READY",
        qualification=QualificationStatus.QUALIFIED,
        owner="Asha",
        tags=("q4-pilot",),
        signal_type="product_launch",
        signal_strength=78,
        signal_age_days=18,
        icp_facts=("Industry: AI SaaS, a B2B software company.", "Location: Pune, India, inside the target market.", "Team size: 16 people, inside the 10-50 range."),
        hypotheses=("Selling an enterprise tier means longer deals, which makes picking the right accounts matter more.",),
        summary="SignalForge AI fits the ICP and launched an enterprise tier 18 days ago.",
        recommended_problem="An enterprise tier needs a different, better-researched target list.",
        recommended_offer="A human-reviewed shortlist of enterprise accounts for the new tier.",
        recommended_action="Review the draft below and send it yourself if it reads right.",
        next_research_step="Look for the first named enterprise customer of the new tier.",
        risks=("A launch announcement says nothing about how the tier is selling.",),
    ),
    _Spec(
        name="CloudKite",
        domain="cloudkite.example",
        industry="Developer SaaS",
        location="Hyderabad, India",
        employee_band="21-50",
        industry_match=88,
        size_match=92,
        geography_match=100,
        pages=(
            _Page("/", "CloudKite - preview environments for every pull request", "CloudKite is a cloud platform that spins up a preview environment for every pull request.", "CloudKite sells a developer cloud platform."),
            _Page("/about", "About CloudKite", "CloudKite is headquartered in Hyderabad, India, and employs 44 people.", "CloudKite is based in Hyderabad with 44 employees."),
            _Page("/news/singapore", "CloudKite opens in Singapore", "CloudKite has opened a Singapore office to serve its growing base of Southeast Asian customers.", "CloudKite expanded into Southeast Asia.", "signal"),
        ),
        attempts=(("/", RetrievalOutcome.RETRIEVED, None), ("/about", RetrievalOutcome.RETRIEVED, None), ("/news/singapore", RetrievalOutcome.RETRIEVED, None)),
        import_source=None,
        brief_state="FOUNDER_READY",
        qualification=QualificationStatus.QUALIFIED,
        owner="Ravi",
        tags=("q4-pilot", "apac"),
        signal_type="expansion",
        signal_strength=70,
        signal_age_days=34,
        icp_facts=("Industry: developer SaaS, a B2B software company.", "Location: Hyderabad, India, inside the target market.", "Team size: 44 people, inside the 10-50 range."),
        hypotheses=("A new region means a new list of target accounts nobody on the team knows yet.",),
        summary="CloudKite fits the ICP and opened a Singapore office 34 days ago; the signal is older, so intent is lower.",
        recommended_problem="Entering a new region with no local account knowledge.",
        recommended_offer="A human-reviewed Southeast Asia account shortlist.",
        recommended_action="Review the draft below and send it yourself if it reads right.",
        next_research_step="Confirm who leads the Singapore office before reaching out.",
        risks=("The expansion is 34 days old; the planning window may have passed.",),
    ),
    _Spec(
        name="Brightwave Analytics",
        domain="brightwave.example",
        industry=None,
        location=None,
        employee_band=None,
        industry_match=None,
        size_match=None,
        geography_match=None,
        pages=(
            _Page("/careers", "Careers at Brightwave", "Brightwave is hiring a founding sales lead to own revenue from our first hundred customers.", "Brightwave is hiring its first sales lead.", "signal"),
        ),
        attempts=(("/", RetrievalOutcome.TIMED_OUT, "The homepage did not respond within the time limit."), ("/about", RetrievalOutcome.TIMED_OUT, "The about page did not respond within the time limit."), ("/careers", RetrievalOutcome.RETRIEVED, None), ("/customers", RetrievalOutcome.NOT_FOUND, "No customers page on this site.")),
        import_source=AccountImportSource.PASTED_DOMAINS,
        brief_state="RESEARCH_CANDIDATE",
        qualification=QualificationStatus.QUALIFIED_WITH_UNCERTAINTY,
        tags=("inbound",),
        signal_type="hiring",
        signal_strength=82,
        signal_age_days=5,
        icp_unknowns=("Industry: the homepage timed out, so what Brightwave sells is not established.", "Location: no page that loaded says where the company is.", "Team size: no page that loaded states it."),
        unknowns=("What Brightwave sells", "Where Brightwave is based", "How many people work there"),
        summary="Brightwave posted a sales-lead role five days ago, but its homepage and about page timed out, so fit is not determined.",
        recommended_problem="Fit is unknown, so there is nothing yet to base a message on.",
        recommended_action="Re-run research before deciding anything.",
        next_research_step="Retry the homepage and about page, which timed out, to establish industry, location and size.",
        risks=("A strong signal on a company whose fit is unknown is a reason to research, not to reach out.",),
    ),
    _Spec(
        name="Harbor Ledger",
        domain="harborledger.example",
        industry="B2B SaaS",
        location="Chennai, India",
        employee_band="51-100",
        industry_match=92,
        size_match=40,
        geography_match=100,
        pages=(
            _Page("/", "Harbor Ledger - payroll compliance software", "Harbor Ledger is a B2B SaaS product that keeps payroll compliant across Indian states.", "Harbor Ledger sells B2B SaaS for payroll compliance."),
            _Page("/about", "About Harbor Ledger", "Harbor Ledger is based in Chennai, India, and has a team of 72 people.", "Harbor Ledger is based in Chennai with a 72-person team."),
        ),
        attempts=(("/", RetrievalOutcome.RETRIEVED, None), ("/about", RetrievalOutcome.RETRIEVED, None), ("/careers", RetrievalOutcome.NOT_FOUND, "No careers page on this site."), ("/news", RetrievalOutcome.NOT_FOUND, "No news page on this site.")),
        import_source=AccountImportSource.SINGLE,
        brief_state="MONITOR",
        qualification=QualificationStatus.QUALIFIED,
        owner="Ravi",
        icp_facts=("Industry: B2B SaaS, as the ICP requires.", "Location: Chennai, India, inside the target market."),
        icp_mismatches=("Team size: 72 people, above the 10-50 range the ICP targets.",),
        summary="Harbor Ledger is a reasonable fit, but nothing on its site shows a current reason to reach out.",
        recommended_problem="No current event to anchor a message to.",
        recommended_action="Monitor. Re-research next month or when news appears.",
        next_research_step="Re-run research in 30 days to look for hiring or launch news.",
        risks=("Messaging without a current reason is what this tool is built to avoid.",),
    ),
    _Spec(
        name="Quillfront",
        domain="quillfront.example",
        industry="Legal tech SaaS",
        location=None,
        employee_band=None,
        industry_match=80,
        size_match=None,
        geography_match=None,
        pages=(
            _Page("/", "Quillfront - contract workflows for in-house legal", "Quillfront is a software platform that helps in-house legal teams draft, review and approve contracts.", "Quillfront sells contract software to in-house legal teams."),
        ),
        attempts=(("/", RetrievalOutcome.RETRIEVED, None), ("/about", RetrievalOutcome.NOT_FOUND, "No about page on this site."), ("/careers", RetrievalOutcome.NOT_FOUND, "No careers page on this site.")),
        import_source=AccountImportSource.CSV_UPLOAD,
        brief_state="IDENTITY_REVIEW_REQUIRED",
        qualification=QualificationStatus.INSUFFICIENT_EVIDENCE,
        tags=("needs-review",),
        icp_facts=("Industry: legal tech SaaS, a B2B software company.",),
        icp_unknowns=("Location: not stated on any official page.", "Team size: not stated on any official page."),
        unknowns=("Whether quillfront.test is the same company", "Where Quillfront is based", "How many people work there"),
        summary="A $25M Series B headline looked like a perfect signal. It came from a different domain, so it was held back for a human to check.",
        recommended_problem="The only signal may belong to another company.",
        recommended_action="Confirm whether quillfront.test belongs to this company before using its news.",
        next_research_step="Check the official site for a link to quillfront.test, or ask the company.",
        reason_not_to_target="The only current event comes from a domain not proven to be this company.",
        risks=("Messaging a company about a funding round it never raised is the mistake this gate exists to prevent.",),
        lookalikes=(
            ("https://quillfront.test/press/series-b", "Quillfront raises $25M Series B", "Quillfront today announced a $25M Series B to expand its contract platform across Europe."),
            ("https://quillfrontgroup.example/investors", "Quillfront Group annual results", "Quillfront Group reported record annual revenue across its legal and compliance businesses."),
        ),
    ),
)


def build_demo_accounts(icp: ICP, now: datetime) -> list[tuple[Account, AccountOpportunityBrief]]:
    return [_build(spec, icp, now, rank) for rank, spec in enumerate(SPECS)]


def _build(spec: _Spec, icp: ICP, now: datetime, rank: int) -> tuple[Account, AccountOpportunityBrief]:
    workspace_id = icp.workspace_id
    account_id = _id("acct")
    observed = now - timedelta(days=spec.signal_age_days)
    sources: list[SourceDocument] = []
    facts: list[EvidenceFact] = []
    fact_claims: list[EvidenceClaim] = []
    signals: list[Signal] = []
    for page in spec.pages:
        url = HttpUrl(f"https://{spec.domain}{page.path}")
        source = SourceDocument(id=_id("src"), workspace_id=workspace_id, platform="web", source_type="webpage", backend="fixture", url=url, canonical_url=url, title=page.title, published_at=observed if page.kind == "signal" else None, retrieved_at=now - timedelta(hours=rank + 1), trust_score=0.9, demo_data=True)
        fact = EvidenceFact(id=_id("ev"), workspace_id=workspace_id, source_id=source.id, passage=page.passage, claim=page.claim, confidence=0.9, status=ClaimStatus.SUPPORTED, observed_at=observed if page.kind == "signal" else now)
        sources.append(source)
        facts.append(fact)
        claim = EvidenceClaim(statement=page.claim, status=ClaimStatus.SUPPORTED, confidence=fact.confidence, evidence_ids=[fact.id])
        if page.kind == "signal":
            signals.append(Signal(id=_id("sig"), signal_type=spec.signal_type or "event", description=page.claim, observed_at=observed, strength=spec.signal_strength / 100, evidence_ids=[fact.id], entity_match_score=1.0, event_confidence=0.9, relevance=spec.signal_strength / 100, source_role=SOURCE_ROLE_FIRST_PARTY, subject_entity=spec.name, canonical_subject_domain=spec.domain, event_date=observed, source_id=source.id, supporting_passage=page.passage, claim_scope="COMPANY_LEVEL", claim_scope_compatible=True, attachment_decision="ATTACHED"))
        else:
            fact_claims.append(claim)

    identity, rejected = _identity_and_rejections(spec)
    retrieval = RetrievalSummary(
        attempted=len(spec.attempts),
        retrieved=sum(1 for _, outcome, _ in spec.attempts if outcome is RetrievalOutcome.RETRIEVED),
        attempts=[RetrievalAttempt(url=f"https://{spec.domain}{path}", outcome=outcome, detail=detail) for path, outcome, detail in spec.attempts],
    )
    fit_ids = [item.evidence_ids[0] for item in fact_claims]
    signal_ids = [item for signal in signals for item in signal.evidence_ids]
    scores = score_account(
        industry_match=spec.industry_match,
        size_match=spec.size_match,
        geography_match=spec.geography_match,
        signal_strength=spec.signal_strength if signals else 0,
        signal_recency=signal_decay(observed) * 100 if signals else None,
        evidence_coverage=min(95, 40 + 15 * len(facts)),
        source_quality=88,
        fit_evidence=fit_ids,
        signal_evidence=signal_ids,
        retrieval_coverage=retrieval.coverage,
    )
    band_name, _ = priority_band(scores, qualification_status=spec.qualification.value, has_verified_signal=bool(signals))
    band = cast(PriorityBand, band_name)
    founder_ready = spec.brief_state == "FOUNDER_READY"
    account = Account(
        id=account_id,
        workspace_id=workspace_id,
        icp_id=icp.id,
        name=spec.name,
        domain=spec.domain,
        industry=spec.industry or "Industry not determined",
        location=spec.location or "Location not determined",
        employee_band=spec.employee_band or "Not determined",
        scores=scores,
        top_signal=signals[0].description if signals else ("Funding headline held back: source not verified as this company" if rejected else "No verified current signal"),
        top_signal_type=signals[0].signal_type if signals else None,
        recommended_action=spec.recommended_action,
        last_researched_at=now - timedelta(hours=rank + 1),
        qualification_status=spec.qualification,
        qualification_reasons=list(spec.icp_mismatches or spec.icp_unknowns),
        company_size_status=CompanySizeStatus.VERIFIED if spec.employee_band else CompanySizeStatus.UNKNOWN,
        discovery_source=f"import:{spec.import_source.value.lower()}" if spec.import_source else "icp_discovery",
        domain_validation="VERIFIED",
        evidence_ids=[item.id for item in facts],
        source_ids=[item.id for item in sources],
        registrable_domain=spec.domain,
        domain_confidence=0.98,
        qualification_coverage=round(sum(value is not None for value in (spec.industry_match, spec.size_match, spec.geography_match)) / 3, 2),
        priority_band=band,
        research_candidate=not founder_ready,
        brief_state=spec.brief_state,
        company_identity=identity.as_persisted_dict(),
        import_source=spec.import_source,
        provenance="IMPORTED" if spec.import_source else "DISCOVERED",
        owner=spec.owner,
        tags=list(spec.tags),
    )
    campaign = CampaignDraft(
        id=_id("camp"),
        account_id=account_id,
        subject=f"Choosing the next accounts for {spec.name}" if founder_ready else "",
        body=(
            f"Hi {spec.name} team,\n\n"
            f"I saw this on your site: {signals[0].description} "
            "Kubu Works helps small teams decide which accounts to approach, with every reason linked to a public source.\n\n"
            "Would a short pilot on your next segment be useful? Happy to share a sample first.\n\n"
            "(Draft only. Nothing is sent by this product.)"
        ) if founder_ready and signals else "",
        evidence_ids=signal_ids if founder_ready else [],
    )
    hypotheses = [EvidenceClaim(statement=item, status=ClaimStatus.HYPOTHESIS, confidence=0.55, evidence_ids=[]) for item in spec.hypotheses]
    signal_claims = [EvidenceClaim(statement=item.description, status=ClaimStatus.SUPPORTED, confidence=0.9, evidence_ids=item.evidence_ids) for item in signals]
    brief = AccountOpportunityBrief(
        account=account,
        why_it_fits=fact_claims,
        why_now=signal_claims,
        pain_hypotheses=hypotheses,
        recommended_problem=spec.recommended_problem,
        recommended_offer=spec.recommended_offer,
        recommended_action=spec.recommended_action,
        executive_summary=spec.summary,
        risks=[_DEMO_RISK, *spec.risks],
        evidence=facts,
        sources=sources,
        signals=signals,
        campaign=campaign,
        verified_facts=fact_claims,
        unknowns=list(spec.unknowns),
        research_candidate=not founder_ready,
        brief_state=spec.brief_state,
        verified_identity=identity.as_persisted_dict(),
        verified_icp_facts=[EvidenceClaim(statement=item, status=ClaimStatus.SUPPORTED, confidence=0.9, evidence_ids=fit_ids) for item in spec.icp_facts],
        icp_mismatches=list(spec.icp_mismatches),
        unknown_icp_facts=list(spec.icp_unknowns),
        current_signals=signals,
        rejected_or_ambiguous_evidence=rejected,
        hypotheses=hypotheses,
        reason_not_to_target=spec.reason_not_to_target,
        next_research_step=spec.next_research_step,
        retrieval=retrieval,
    )
    return account, brief


def _identity_and_rejections(spec: _Spec) -> tuple[CompanyIdentityRecord, list[dict[str, object]]]:
    """Run the real entity-safety gate over each lookalike passage.

    Quillfront has a verified parent, so its group-level results are a known
    company's real news -- just not this company's. The `.test` press release
    shares the brand name and has no proven link at all. The gate tells those two
    apart; the demo only supplies the inputs.
    """
    relationships: tuple[VerifiedEntityRelationship, ...] = ()
    if spec.lookalikes:
        relationships = (
            VerifiedEntityRelationship(
                subject_domain="quillfrontgroup.example",
                object_domain=spec.domain,
                relation=EntityRelation.PARENT_OF,
                evidence_ids=("ev_demo_parent_disclosure",),
            ),
        )
    identity = CompanyIdentityRecord(
        canonical_company_name=spec.name,
        canonical_registrable_domain=spec.domain,
        verified_official_domains=(spec.domain,),
        relationships=relationships,
        identity_confidence=0.98,
        unresolved_identity_warnings=("One or more sources may belong to another entity.",) if spec.lookalikes else (),
    )
    rejected: list[dict[str, object]] = []
    for url, title, passage in spec.lookalikes:
        assessment = assess_evidence_attachment(identity, source_url=url, source_role=SOURCE_ROLE_FIRST_PARTY, source_title=title, passage=passage)
        rejected.append(
            {
                "evidence_id": _id("ev"),
                "source_domain": assessment.source_domain,
                "source_url": url,
                "passage": passage,
                "subject": assessment.subject_entity,
                "relation": assessment.relation.value,
                "scope": assessment.claim_scope.value,
                "decision": assessment.decision.value,
                "reason": assessment.reason,
            }
        )
    return identity, rejected
