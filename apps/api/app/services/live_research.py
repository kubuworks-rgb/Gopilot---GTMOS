from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from urllib.parse import urlsplit

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.config import settings
from apps.api.app.db.models import (
    AccountResearchSnapshotRow,
    AccountRow,
    AccountScoreFactorRow,
    AccountScoreSnapshotRow,
    AgentRunRow,
    ApprovalRequestRow,
    CampaignDraftRow,
    EvidenceFactRow,
    GTMFindingRow,
    ICPProfileRow,
    IntentSignalRow,
    OpportunityBriefRow,
    ProductProfileRow,
    ResearchRunRow,
    ResearchCandidateRow,
    ResearchTaskRow,
    SourceChunkRow,
    SourceDocumentRow,
    ToolCallRow,
)
from apps.api.app.db.session import SessionFactory
from apps.api.app.domain.models import (
    AccountOpportunityBrief,
    CampaignDraft,
    ClaimStatus,
    EvidenceClaim,
    RetrievalAttempt,
    RetrievalOutcome,
    RetrievalSummary,
    Signal,
)
from apps.api.app.providers.live import GatewayProviderError, LiveResearchProvider
from apps.api.app.repositories.postgres import repository
from apps.api.app.services.scoring import score_account, signal_decay
from apps.api.app.services.scoring import priority_band
from apps.api.app.services.company_identity import (
    CompanyDomainIdentity,
    ResultPageRole,
    classify_result_page,
    resolve_company_identity,
)
from apps.api.app.services.byoa import search_provider_configured
from apps.api.app.services.firmographics import PublicEvidenceFirmographicProvider
from apps.api.app.services.entity_resolution import (
    AttachmentDecision,
    BriefState,
    ClaimScope,
    CompanyIdentityRecord,
    EntityRelation,
    EvidenceAttachmentAssessment,
    IMPORT_PENDING_IDENTITY_WARNING,
    VerifiedAlias,
    VerifiedEntityRelationship,
    assess_evidence_attachment,
    decide_brief_state,
)
from apps.api.app.services.intelligence_quality import (
    CandidatePrequalificationDecision,
    CandidatePrequalificationInput,
    CompetitorAssessment,
    CompetitorClassification,
    CriterionEvaluation,
    CriterionRequirement,
    CriterionState,
    EvidenceStage,
    MatchState,
    PrequalificationOutcome,
    SourceRole,
    candidate_relevance_breakdown,
    decide_qualification,
    evaluate_prequalification,
    source_quality_score,
)
from services.research_gateway.app.schemas import SearchResult, SourceDocumentInput


FINDING_CATEGORIES = ("market", "competitor", "pain_point", "buying_trigger")
SIGNAL_RULES = {
    "SUPPORT_HIRING": (
        ("support", "customer service"),
        ("hiring", "job opening", "open role", "join our team", "vacancy"),
    ),
    "CUSTOMER_SUCCESS_HIRING": (
        ("customer success",),
        ("hiring", "job opening", "open role", "join our team", "vacancy"),
    ),
    "SALES_EXPANSION": (
        ("sales", "go-to-market", "revenue team"),
        ("hiring", "expansion", "expanding", "new office"),
    ),
    "FUNDING": (("funding", "raised", "series a", "series b", "seed round"),),
    "NEW_MARKET": (("new market", "market expansion", "expanding into", "new region"),),
    "NEW_PRODUCT": (("launched", "launches", "new product", "now available"),),
    "PARTNERSHIP": (("partnership", "partnered", "strategic alliance"),),
    "LEADERSHIP_CHANGE": (
        ("appointed", "named"),
        ("chief executive", "chief revenue", "chief customer", "vice president"),
    ),
    "ENTERPRISE_EXPANSION": (
        ("enterprise",),
        ("expansion", "new tier", "new offering", "launched"),
    ),
    "TECHNOLOGY_CHANGE": (
        ("migration", "migrated", "adopted", "technology stack", "platform change"),
    ),
    "CUSTOMER_GROWTH_INDICATOR": (
        ("customers", "users", "businesses"),
        ("grew", "growth", "serves", "trusted by", "crossed"),
    ),
}
EXCLUDED_ACCOUNT_HOSTS = {
    "bing.com",
    "www.bing.com",
    "linkedin.com",
    "www.linkedin.com",
    "wikipedia.org",
    "en.wikipedia.org",
    "youtube.com",
    "www.youtube.com",
    "github.com",
    "www.github.com",
    "crunchbase.com",
    "www.crunchbase.com",
    "g2.com",
    "www.g2.com",
    "capterra.com",
    "www.capterra.com",
    "tracxn.com",
    "www.tracxn.com",
    "yourstory.com",
    "www.yourstory.com",
    "inc42.com",
    "www.inc42.com",
    "economictimes.indiatimes.com",
    "medium.com",
    "www.medium.com",
    "substack.com",
    "www.substack.com",
    "glassdoor.com",
    "www.glassdoor.com",
    "ambitionbox.com",
    "www.ambitionbox.com",
}
WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9-]{2,}")
SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")
BOILERPLATE_TERMS = (
    "log into your account",
    "forgot your password",
    "password recovery",
    "sign in",
    "cookie policy",
    "privacy policy",
    "all rights reserved",
    "internal link incorrectly led",
    "personal, non-commercial use",
    "accessibility menu",
    "open sidebar ad",
)
# Phrases that only ever appear in site chrome, never in a claim about a company.
NAVIGATION_MARKERS = (
    "skip to main content",
    "skip to content",
    "main navigation",
    "toggle theme",
    "toggle navigation",
    "current theme",
    "back to top",
    "site map",
    "sitemap",
    "follow us",
    "get involved",
    "search submit",
    "open menu",
    "close menu",
    "breadcrumb",
    "share this",
    "subscribe to our newsletter",
)
# Qualification notes that mention a mismatch term while explicitly declining to
# assert one. Presenting these as mismatches misreports the system's own finding.
NON_MISMATCH_MARKERS = (
    "no automatic rejection",
    "requires research",
    "remains unknown",
    "not treated as false",
)
SOURCE_CHUNK_SIZE = 1800
SOURCE_CHUNK_STEP = 1100


@dataclass
class DiscoveryCandidate:
    result: SearchResult
    identity: CompanyDomainIdentity
    queries: set[str]
    providers: set[str]
    score: int = 0
    prequalification: CandidatePrequalificationDecision | None = None
    score_diagnostics: dict[str, object] | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _attribute_string_list(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _tokens(value: str) -> set[str]:
    return {
        match.group(0).lower()
        for match in WORD_PATTERN.finditer(value)
        if match.group(0).lower()
        not in {"and", "the", "for", "with", "from", "that", "this", "into"}
    }


def _sentences(text: str) -> list[str]:
    """Split into passage-sized candidates.

    Segments longer than the cap are clamped at a word boundary rather than
    discarded. Plenty of real company pages carry very little sentence
    punctuation, and dropping their whole body left the account with no evidence
    at all -- which then read as "the domain could not be verified" even though it
    had been fetched successfully.
    """

    passages: list[str] = []
    for raw in SENTENCE_PATTERN.split(text):
        value = raw.strip()
        if len(value) < 45:
            continue
        if len(value) <= 700:
            passages.append(value)
            continue
        clipped = value[:700]
        boundary = clipped.rfind(" ")
        passages.append(clipped[:boundary] if boundary > 45 else clipped)
    return passages


def _is_boilerplate_passage(text: str) -> bool:
    """Reject navigation and footer chrome before it can be shown as a fact.

    A menu blob is not a claim about a company. Presenting one as SUPPORTED
    evidence inverts the product's entire promise, so this errs toward rejecting:
    one fewer fact beats a brief that cites "Toggle theme" as a verified fact.
    Identity verification no longer depends on extracting a passage, so being
    strict here costs nothing.
    """

    lowered = text.lower()
    if any(term in lowered for term in BOILERPLATE_TERMS):
        return True
    if any(term in lowered for term in NAVIGATION_MARKERS):
        return True

    words = text.split()
    if len(words) < 6:
        return True

    # Link runs are long and almost unpunctuated; real prose is not.
    punctuation = sum(text.count(mark) for mark in ".,;:!?")
    if len(words) >= 25 and punctuation <= 1:
        return True

    # Menus are overwhelmingly Title Case; sentences are not.
    following = words[1:]
    capitalised = sum(1 for word in following if word[:1].isupper())
    if len(words) >= 12 and capitalised / max(1, len(following)) > 0.5:
        return True

    return False


GEOGRAPHY_VOCABULARY: dict[str, tuple[str, ...]] = {
    "india": (
        "india", "indian", "bengaluru", "bangalore", "hyderabad", "pune",
        "mumbai", "delhi", "chennai", "noida", "gurugram",
    ),
    "united states": (
        "united states", "u.s.", "usa", "san francisco", "new york", "boston",
        "austin", "seattle", "chicago", "denver",
    ),
    "united kingdom": ("united kingdom", "britain", "british", "london", "manchester"),
    "europe": (
        "europe", "european", "berlin", "paris", "amsterdam", "dublin",
        "madrid", "stockholm", "munich",
    ),
    "apac": ("apac", "asia-pacific", "singapore", "tokyo", "seoul"),
    "australia": ("australia", "australian", "sydney", "melbourne"),
    "canada": ("canada", "canadian", "toronto", "vancouver", "montreal"),
}


def _target_geography_terms(target_market: str) -> tuple[str, ...]:
    """Geography vocabulary implied by the founder's own target market.

    Previously hardcoded to Indian cities, so a founder targeting anywhere else
    could never score geography above zero no matter what the evidence said.
    """

    lowered = target_market.lower()
    terms: list[str] = []
    for region, vocabulary in GEOGRAPHY_VOCABULARY.items():
        if region in lowered or any(term in lowered for term in vocabulary):
            terms.extend(vocabulary)
    return tuple(dict.fromkeys(terms))


def _usable_passages(text: str) -> list[str]:
    """Passages that read as claims rather than site furniture."""

    return [item for item in _sentences(text) if not _is_boilerplate_passage(item)]


def _evidence_passages(text: str, context: str) -> list[str]:
    context_tokens = _tokens(context)
    minimum_overlap = 1 if len(context_tokens) <= 3 else 2
    ranked: list[tuple[int, float, int, str]] = []
    for index, sentence in enumerate(_sentences(text)):
        if _is_boilerplate_passage(sentence):
            continue
        sentence_tokens = _tokens(sentence)
        overlap = len(context_tokens & sentence_tokens)
        if overlap < minimum_overlap:
            continue
        coverage = overlap / max(1, len(context_tokens))
        ranked.append((overlap, coverage, -index, sentence))
    ranked.sort(reverse=True)
    return [item[3] for item in ranked[:2]]


def _content_hash(text: str) -> str:
    normalized = " ".join(text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _error_payload(exc: GatewayProviderError) -> dict[str, object]:
    return {
        "category": exc.category,
        "message": exc.safe_message,
        "retryable": exc.retryable,
    }


def build_research_queries(product: ProductProfileRow) -> list[str]:
    return [
        f"{product.product} {product.target_market} market trends",
        f"{product.product} competitors alternatives India",
        f"{product.target_market} customer support pain points",
        f"{product.target_market} support hiring expansion buying triggers",
        f"{product.target_market} companies official websites",
        "AI support automation India SaaS funding launch partnership",
    ][: settings.max_research_searches]


RESEARCH_INTENTS = (
    "MARKET_LANDSCAPE",
    "COMPETITOR_DISCOVERY",
    "ICP_EVIDENCE",
    "ICP_EVIDENCE",
    "ACCOUNT_DISCOVERY",
    "ACCOUNT_SIGNAL_RESEARCH",
)


def build_research_plan(
    product: ProductProfileRow,
) -> list[tuple[str, str, str]]:
    return [
        (
            RESEARCH_INTENTS[index],
            query,
            "news"
            if RESEARCH_INTENTS[index] == "ACCOUNT_SIGNAL_RESEARCH"
            else "market_research",
        )
        for index, query in enumerate(build_research_queries(product))
    ]


async def _persist_source(
    session: AsyncSession,
    run: ResearchRunRow,
    source: SourceDocumentInput,
    evidence_context: str | None = None,
) -> tuple[SourceDocumentRow, list[EvidenceFactRow]]:
    digest = _content_hash(source.text)
    existing = await session.scalar(
        select(SourceDocumentRow).where(
            SourceDocumentRow.research_run_id == run.id,
            SourceDocumentRow.content_hash == digest,
            SourceDocumentRow.canonical_url == str(source.canonical_url),
        )
    )
    if existing is not None:
        existing_facts = list(
            (
                await session.scalars(
                    select(EvidenceFactRow).where(
                        EvidenceFactRow.source_id == existing.id
                    )
                )
            ).all()
        )
        return existing, existing_facts
    page_role = classify_result_page(str(source.canonical_url))
    source_role = {
        ResultPageRole.OFFICIAL_ROOT: SourceRole.FIRST_PARTY,
        ResultPageRole.OFFICIAL_SUBDOMAIN: SourceRole.FIRST_PARTY,
        ResultPageRole.DIRECTORY: SourceRole.DIRECTORY,
        ResultPageRole.NEWS: SourceRole.NEWS,
        ResultPageRole.SOCIAL: SourceRole.COMMUNITY,
        ResultPageRole.VENDOR_MARKETING: SourceRole.VENDOR_MARKETING,
        ResultPageRole.OTHER: SourceRole.OTHER,
    }[page_role]
    parsed_source = urlsplit(str(source.canonical_url))
    marketing_path = any(
        marker in parsed_source.path.lower()
        for marker in ("/blog", "/resources", "/guides", "/reports")
    )
    market_claim_language = any(
        marker in f"{source.title} {source.text[:2000]}".lower()
        for marker in ("market size", "market report", "industry trends")
    )
    if marketing_path and market_claim_language:
        source_role = SourceRole.VENDOR_MARKETING
    entity_match = 0.95 if source_role == SourceRole.FIRST_PARTY else 0.70
    quality = source_quality_score(
        role=source_role,
        directness=0.95 if source_role == SourceRole.FIRST_PARTY else 0.70,
        recency=0.85 if source.published_at else 0.55,
        entity_match=entity_match,
    )
    row = SourceDocumentRow(
        workspace_id=run.workspace_id,
        research_run_id=run.id,
        platform=source.platform,
        source_type=source.source_type,
        backend=source.backend,
        url=str(source.url),
        canonical_url=str(source.canonical_url),
        title=source.title,
        author=source.author,
        published_at=source.published_at,
        retrieved_at=source.retrieved_at,
        language=source.language,
        content_hash=digest,
        cleaned_text=source.text,
        raw_storage_key=None,
        trust_score=quality,
        permission_classification="public",
        status="retrieved",
        provenance={
            "retrieved_by": "research-gateway",
            "backend": source.backend,
            "source_role": source_role.value,
            "source_quality": {
                "score": quality,
                "directness": 0.95
                if source_role == SourceRole.FIRST_PARTY
                else 0.70,
                "recency": 0.85 if source.published_at else 0.55,
                "entity_match": entity_match,
            },
        },
        source_metadata={
            **source.metadata,
            "content_type": source.content_type,
            "normalized_text_length": len(source.text),
        },
    )
    session.add(row)
    await session.flush()
    for ordinal, start in enumerate(range(0, len(source.text), SOURCE_CHUNK_STEP)):
        chunk = source.text[start : start + SOURCE_CHUNK_SIZE]
        session.add(
            SourceChunkRow(
                workspace_id=run.workspace_id,
                source_document_id=row.id,
                ordinal=ordinal,
                text=chunk,
                content_hash=_content_hash(chunk),
                token_estimate=max(1, len(chunk) // 4),
                embedding=None,
            )
        )
    candidates = (
        _evidence_passages(source.text, evidence_context)
        if evidence_context
        else _usable_passages(source.text)[:2]
    )
    # A first-party page that matched no context tokens is still the company
    # describing itself, so fall back to its leading substantive passages. The
    # fallback must apply the same quality gate: it previously did not, which is
    # how navigation blobs reached briefs as SUPPORTED facts.
    if not candidates:
        candidates = _usable_passages(source.text)[:2]
    facts: list[EvidenceFactRow] = []
    for passage in candidates:
        fact = EvidenceFactRow(
            workspace_id=run.workspace_id,
            source_id=row.id,
            subject=source.title[:500],
            predicate="states",
            object=passage,
            claim=passage,
            passage=passage,
            confidence="0.82",
            status=ClaimStatus.SUPPORTED.value,
            observed_at=source.published_at or source.retrieved_at,
            valid_from=source.published_at,
            valid_until=None,
        )
        session.add(fact)
        facts.append(fact)
    await session.flush()
    _validate_evidence(row, facts)
    return row, facts


def _validate_evidence(source: SourceDocumentRow, facts: list[EvidenceFactRow]) -> None:
    for fact in facts:
        if fact.workspace_id != source.workspace_id:
            raise ValueError("Evidence workspace does not match source workspace")
        if fact.passage not in source.cleaned_text:
            raise ValueError("Evidence passage is not present in source content")
        if fact.status != ClaimStatus.HYPOTHESIS.value and not fact.source_id:
            raise ValueError("Supported evidence must reference a source")


async def _tool_call(
    session: AsyncSession,
    run: ResearchRunRow,
    agent_run_id: uuid.UUID,
    tool: str,
    input_summary: dict[str, object],
    started_at: datetime,
    *,
    status: str,
    backend: str | None = None,
    error_category: str | None = None,
) -> None:
    elapsed = max(0, int((_now() - started_at).total_seconds() * 1000))
    session.add(
        ToolCallRow(
            workspace_id=run.workspace_id,
            research_run_id=run.id,
            agent_run_id=agent_run_id,
            tool=tool,
            adapter="research-gateway",
            backend=backend,
            input_summary=input_summary,
            status=status,
            started_at=started_at,
            completed_at=_now(),
            latency_ms=elapsed,
            error_category=error_category,
        )
    )


async def execute_research(
    run_id: str,
    provider: LiveResearchProvider | None = None,
    queries_override: list[str] | None = None,
) -> None:
    provider = provider or LiveResearchProvider()
    async with SessionFactory() as session:
        run = await repository.run_row(session, run_id)
        if run is None:
            return
        product = await session.get(ProductProfileRow, run.product_id)
        if product is None:
            await _fail_run(session, run, "PRODUCT_NOT_FOUND", "Product was removed")
            return
        run.status = "planning"
        run.current_stage = "research_plan"
        agent_run = AgentRunRow(
            workspace_id=run.workspace_id,
            research_run_id=run.id,
            agent_name="live-market-research",
            status="running",
            input_summary={"product_id": str(product.id)},
            output_summary={},
            started_at=_now(),
            completed_at=None,
            error_category=None,
        )
        session.add(agent_run)
        await session.flush()
        plan = (
            [
                ("MARKET_LANDSCAPE", query, "market_research")
                for query in queries_override
            ]
            if queries_override is not None
            else build_research_plan(product)
        )
        workflow_started = monotonic()
        run.status = "researching"
        run.current_stage = "market_intelligence"
        await session.commit()

        all_facts: list[EvidenceFactRow] = []
        failures: list[dict[str, object]] = []
        seen_urls: set[str] = set()
        had_relevant_results = False
        for intent, query, purpose in plan:
            if monotonic() - workflow_started >= settings.max_elapsed_seconds:
                failures.append(
                    {
                        "category": "TIME_BUDGET_EXCEEDED",
                        "message": "Research time budget was reached",
                        "retryable": False,
                    }
                )
                break
            if run.searches_used >= settings.max_research_searches:
                break
            task = ResearchTaskRow(
                workspace_id=run.workspace_id,
                research_run_id=run.id,
                task_type=intent,
                query=query,
                status="running",
                source_strategy={
                    "adapter": "search",
                    "purpose": purpose,
                    "limit": 5,
                },
                result_summary={},
                error=None,
                started_at=_now(),
                completed_at=None,
            )
            session.add(task)
            await session.flush()
            started = _now()
            run.searches_used += 1
            try:
                response = await provider.search(
                    workspace_id=str(run.workspace_id),
                    research_run_id=str(run.id),
                    query=query,
                    limit=min(5, settings.max_research_documents),
                    purpose=purpose,
                )
                await _tool_call(
                    session,
                    run,
                    agent_run.id,
                    "search",
                    {"query": query, "intent": intent, "purpose": purpose},
                    started,
                    status="completed",
                    backend=response.backend,
                )
                usable = 0
                had_relevant_results = had_relevant_results or bool(response.results)
                for result in response.results:
                    if run.documents_used >= settings.max_research_documents:
                        break
                    canonical = str(result.canonical_url)
                    if canonical in seen_urls:
                        continue
                    seen_urls.add(canonical)
                    source, facts = await _fetch_result(
                        session, run, agent_run.id, provider, result, query
                    )
                    if source is None:
                        continue
                    usable += 1
                    run.documents_used += 1
                    all_facts.extend(facts)
                task.status = (
                    "completed" if usable or not response.results else "partial"
                )
                task.result_summary = {
                    "results": len(response.results),
                    "documents": usable,
                    "samples": [
                        {
                            "title": item.title,
                            "domain": (
                                urlsplit(str(item.url)).hostname or ""
                            ).removeprefix("www."),
                            "url": str(item.url),
                            "published_at": (
                                item.published_at.isoformat()
                                if item.published_at is not None
                                else None
                            ),
                            "retrieved_at": item.retrieved_at.isoformat(),
                        }
                        for item in response.results[:3]
                    ],
                    "diagnostics": (
                        response.diagnostics.model_dump(mode="json")
                        if response.diagnostics is not None
                        else None
                    ),
                }
            except GatewayProviderError as exc:
                failure = _error_payload(exc) | {"query": query}
                failures.append(failure)
                task.status = "failed"
                task.error = failure
                await _tool_call(
                    session,
                    run,
                    agent_run.id,
                    "search",
                    {"query": query},
                    started,
                    status="failed",
                    error_category=exc.category,
                )
            task.completed_at = _now()
            await session.commit()

        if not all_facts:
            if not failures and not had_relevant_results:
                agent_run.status = "completed"
                agent_run.output_summary = {
                    "searches": run.searches_used,
                    "documents": 0,
                    "evidence": 0,
                    "partial_failures": 0,
                    "outcome": "NO_RELEVANT_RESULTS",
                }
                agent_run.completed_at = _now()
                run.status = "completed"
                run.current_stage = "no_relevant_results"
                run.error = None
                run.updated_at = _now()
                run.completed_at = _now()
                await session.commit()
                return
            agent_run.status = "failed"
            agent_run.completed_at = _now()
            agent_run.error_category = (
                str(failures[0]["category"]) if failures else "NO_EVIDENCE"
            )
            await _fail_run(
                session,
                run,
                agent_run.error_category,
                "Live research produced no evidence; fixtures were not substituted",
                failures,
            )
            return

        run.status = "extracting"
        run.current_stage = "evidence_extraction"
        categories = list(FINDING_CATEGORIES)
        for index, fact in enumerate(all_facts[:8]):
            category = categories[index % len(categories)]
            fact_source = await session.get(SourceDocumentRow, fact.source_id)
            source_role = (
                str(
                    fact_source.provenance.get("source_role")
                    or SourceRole.OTHER.value
                )
                if fact_source is not None
                else SourceRole.OTHER.value
            )
            incompatible_vendor_market_claim = (
                category == "market"
                and source_role == SourceRole.VENDOR_MARKETING.value
            )
            session.add(
                GTMFindingRow(
                    workspace_id=run.workspace_id,
                    research_run_id=run.id,
                    category=category,
                    claim=fact.claim,
                    confidence=(
                        0.35
                        if incompatible_vendor_market_claim
                        else float(fact.confidence)
                    ),
                    status=(
                        ClaimStatus.HYPOTHESIS.value
                        if incompatible_vendor_market_claim
                        else fact.status
                    ),
                    evidence_ids=(
                        [] if incompatible_vendor_market_claim else [str(fact.id)]
                    ),
                )
            )
        await _create_icps(session, run, product, all_facts)
        run.evidence_count = len(all_facts)
        run.status = "awaiting_icp"
        run.current_stage = "icp_selection"
        run.error = {"partial_failures": failures} if failures else None
        run.updated_at = _now()
        agent_run.status = "completed" if not failures else "partial"
        agent_run.output_summary = {
            "searches": run.searches_used,
            "documents": run.documents_used,
            "evidence": len(all_facts),
            "partial_failures": len(failures),
        }
        agent_run.completed_at = _now()
        await session.commit()


async def _fetch_result(
    session: AsyncSession,
    run: ResearchRunRow,
    agent_run_id: uuid.UUID,
    provider: LiveResearchProvider,
    result: SearchResult,
    evidence_context: str,
) -> tuple[SourceDocumentRow | None, list[EvidenceFactRow]]:
    started = _now()
    try:
        source_input = await provider.fetch(
            workspace_id=str(run.workspace_id),
            research_run_id=str(run.id),
            url=str(result.url),
        )
        source, facts = await _persist_source(
            session,
            run,
            source_input,
            f"{evidence_context} {result.title}",
        )
        await _tool_call(
            session,
            run,
            agent_run_id,
            "fetch",
            {"url": str(result.url)},
            started,
            status="completed",
            backend=source_input.backend,
        )
        return source, facts
    except GatewayProviderError as exc:
        await _tool_call(
            session,
            run,
            agent_run_id,
            "fetch",
            {"url": str(result.url)},
            started,
            status="failed",
            error_category=exc.category,
        )
        return None, []


async def _create_icps(
    session: AsyncSession,
    run: ResearchRunRow,
    product: ProductProfileRow,
    facts: list[EvidenceFactRow],
) -> None:
    existing = await session.scalar(
        select(ICPProfileRow).where(ICPProfileRow.research_run_id == run.id).limit(1)
    )
    if existing is not None:
        return
    evidence = [str(item.id) for item in facts]
    support_product = any(
        term in product.product.lower()
        for term in ("support", "customer service", "customer experience")
    )
    variants: tuple[dict[str, object], ...] = (
        {
            "name": "India mid-market B2B SaaS support scaleups",
            "description": (
                "India-based B2B SaaS companies with 50-500 employees whose "
                "support workload is likely to grow with their customer base."
                if support_product
                else f"Organizations that directly match {product.target_market}."
            ),
            "firmographics": ["B2B SaaS", "India", "50-500 employees"],
            "pains": [
                "Rising support volume may outpace a lean support team",
                "Knowledge consistency and response time require discovery validation",
            ],
            "triggers": [
                "Support or customer-success hiring",
                "Customer growth or enterprise expansion",
            ],
            "recommended": True,
            "qualification_logic": [
                "Official domain is validated",
                "India B2B SaaS evidence is present",
                "50-500 employees is verified or credibly estimated",
            ],
        },
        {
            "name": "Customer-success expansion teams",
            "description": (
                "India B2B SaaS companies expanding customer success or support "
                "capacity and showing a source-backed hiring signal."
            ),
            "firmographics": ["B2B SaaS", "India", "Growth-stage"],
            "pains": [
                "Manual tier-one work may constrain higher-value customer success",
                "Handoffs and support knowledge may fragment as teams expand",
            ],
            "triggers": [
                "Customer-success hiring",
                "New market, funding, or sales expansion",
            ],
            "recommended": False,
            "qualification_logic": [
                "Current support or customer-success hiring evidence exists",
                "Company is not a direct support-automation vendor",
            ],
        },
        {
            "name": "Enterprise-support complexity adopters",
            "description": (
                "India B2B SaaS vendors moving upmarket or launching enterprise "
                "offerings where high-availability support matters."
            ),
            "firmographics": [
                "B2B SaaS",
                "India or India-serving",
                "Enterprise motion",
            ],
            "pains": [
                "Enterprise response expectations may exceed existing workflows",
                "Complex products create repetitive but context-heavy questions",
            ],
            "triggers": [
                "Enterprise product launch",
                "New market, partnership, or technology change",
            ],
            "recommended": False,
            "qualification_logic": [
                "Enterprise or upmarket motion is source-supported",
                "A current change event is verified",
            ],
        },
    )
    for index, variant in enumerate(variants):
        selected_evidence = [evidence[index % len(evidence)]]
        session.add(
            ICPProfileRow(
                workspace_id=run.workspace_id,
                research_run_id=run.id,
                name=str(variant["name"])[:120],
                description=str(variant["description"]),
                definition={
                    "criteria_version": "supportpilot-icp-v2",
                    "criteria": [
                        {
                            "key": "official_domain",
                            "requirement": "HARD",
                            "unknown_policy": "RESEARCH_REQUIRED",
                        },
                        {
                            "key": "b2b_software",
                            "requirement": "HARD",
                            "unknown_policy": "RESEARCH_REQUIRED",
                        },
                        {
                            "key": "india_connection",
                            "requirement": "HARD",
                            "unknown_policy": "RESEARCH_REQUIRED",
                        },
                        {
                            "key": "not_direct_competitor",
                            "requirement": "HARD",
                            "unknown_policy": "RESEARCH_REQUIRED",
                        },
                        {
                            "key": "support_operations",
                            "requirement": "SOFT",
                            "unknown_policy": "NO_PENALTY",
                        },
                        {
                            "key": "employee_preference",
                            "requirement": "SOFT",
                            "unknown_policy": "NO_PENALTY",
                        },
                    ],
                    "firmographics": variant["firmographics"],
                    "pains": variant["pains"],
                    "triggers": variant["triggers"],
                    "recommended": variant["recommended"],
                    "qualification_logic": variant["qualification_logic"],
                    "rationale": (
                        "Combines the user-confirmed target definition with "
                        "source-backed market context. Pain statements remain "
                        "hypotheses until account-level evidence or discovery."
                    ),
                },
                confidence=0.84 if index == 0 else 0.76,
                evidence_ids=selected_evidence,
                selected_at=None,
            )
        )


async def _fail_run(
    session: AsyncSession,
    run: ResearchRunRow,
    category: str,
    message: str,
    details: list[dict[str, object]] | None = None,
) -> None:
    run.status = "failed"
    run.current_stage = "failed"
    run.error = {
        "category": category,
        "message": message,
        "details": details or [],
    }
    run.updated_at = _now()
    run.completed_at = _now()
    await session.commit()


def _normalized_company_domain(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    if not host:
        return None
    if host in EXCLUDED_ACCOUNT_HOSTS or any(
        host.endswith(f".{excluded.removeprefix('www.')}")
        for excluded in EXCLUDED_ACCOUNT_HOSTS
    ):
        return None
    return resolve_company_identity(url).canonical_company_domain


def _is_candidate_company_page(result: SearchResult) -> bool:
    if classify_result_page(str(result.url)) not in {
        ResultPageRole.OFFICIAL_ROOT,
        ResultPageRole.OFFICIAL_SUBDOMAIN,
    }:
        return False
    parsed = urlsplit(str(result.url))
    path = parsed.path.strip("/").lower()
    first_segment = path.split("/", 1)[0] if path else ""
    allowed_segments = {
        "",
        "about",
        "about-us",
        "company",
        "team",
        "who-we-are",
        "careers",
        "home",
    }
    title = result.title.lower()
    rejected_title_terms = (
        "top ",
        "best ",
        "list of",
        "comparison",
        "alternatives",
        "review",
        "financials",
        "profile 202",
        "companies in india",
    )
    return first_segment in allowed_segments and not any(
        term in title for term in rejected_title_terms
    )


def _discovery_prequalification_input(
    candidate: DiscoveryCandidate,
) -> CandidatePrequalificationInput:
    # Provider queries describe what GoPilot requested, not what the result
    # company actually is. Including them here makes every candidate look like
    # B2B SaaS and destroys the uncertainty/review distinction.
    discovery_text = " ".join(
        [candidate.result.title, candidate.result.snippet]
    ).lower()
    plausible_software = any(
        term in discovery_text
        for term in (
            "b2b",
            "saas",
            "software",
            "cloud",
            "platform",
            "developer tools",
            "product analytics",
        )
    )
    plausible_saas = any(
        term in discovery_text for term in ("saas", "cloud", "software platform")
    )
    plausible_india = any(
        term in discovery_text
        for term in (
            "india",
            "bengaluru",
            "bangalore",
            "hyderabad",
            "pune",
            "mumbai",
            "gurugram",
            "gurgaon",
            "chennai",
            "noida",
        )
    )
    identity_state = (
        MatchState.VERIFIED_MATCH
        if (
            candidate.identity.page_role == ResultPageRole.OFFICIAL_ROOT
            and candidate.identity.confidence >= 0.85
        )
        else MatchState.ESTIMATED_MATCH
    )
    domain_state = (
        MatchState.VERIFIED_MATCH
        if candidate.identity.confidence >= 0.85
        else MatchState.ESTIMATED_MATCH
    )
    return CandidatePrequalificationInput(
        page_role=candidate.identity.page_role.value,
        duplicate=False,
        identity_state=identity_state,
        identity_confidence=candidate.identity.confidence,
        domain_state=domain_state,
        b2b_software_state=(
            MatchState.ESTIMATED_MATCH if plausible_software else MatchState.UNKNOWN
        ),
        saas_state=(
            MatchState.ESTIMATED_MATCH if plausible_saas else MatchState.UNKNOWN
        ),
        india_state=(
            MatchState.ESTIMATED_MATCH if plausible_india else MatchState.UNKNOWN
        ),
        employee_size_state=MatchState.UNKNOWN,
        support_operations_state=MatchState.UNKNOWN,
        category_relevance=candidate.score,
        evidence_stage=EvidenceStage.DISCOVERY_HINT,
        evidence_coverage=0,
        competitor=CompetitorAssessment(CompetitorClassification.UNKNOWN),
    )


def _company_size_from_text(text: str) -> tuple[str | None, str, bool | None]:
    patterns = (
        (
            r"\b(?:we\s+(?:have|employ)|our\s+(?:company|team|workforce)\s+"
            r"(?:has|includes)?|(?:company|team|workforce)\s+of|employs)\s+"
            r"(\d{1,5})\s*[-–]\s*(\d{1,5})\s+"
            r"(?:employees|people|team members)\b"
        ),
        (
            r"\b(?:we\s+(?:have|employ)|our\s+(?:company|team|workforce)\s+"
            r"(?:has|includes)?|(?:company|team|workforce)\s+of|employs)\s+"
            r"(\d{1,5})\+?\s+(?:employees|people|team members)\b"
        ),
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        low = int(match.group(1))
        high = int(match.group(2)) if match.lastindex == 2 else low
        in_range = high >= 50 and low <= 500
        band = f"{low}-{high}" if low != high else f"{low}+"
        return band, "VERIFIED", in_range
    return None, "UNKNOWN", None


def _competitor_assessment_from_text(
    text: str,
    *,
    evidence_ids: tuple[str, ...] = (),
) -> CompetitorAssessment:
    lowered = text.lower()
    dimensions: list[str] = []
    product_overlap = (
        any(term in lowered for term in ("customer support", "customer service"))
        and any(term in lowered for term in ("ai", "automation", "agent"))
        and any(term in lowered for term in ("platform", "software", "solution"))
    )
    buyer_overlap = any(
        term in lowered
        for term in (
            "support teams",
            "customer service teams",
            "customer experience teams",
            "b2b saas",
            "enterprise teams",
        )
    )
    use_case_overlap = any(
        term in lowered
        for term in (
            "resolve tickets",
            "ticket resolution",
            "automate customer support",
            "support automation",
            "answer customer queries",
        )
    )
    commercial_substitution = any(
        term in lowered
        for term in (
            "replace your helpdesk",
            "customer support platform",
            "ai support platform",
            "support automation platform",
        )
    )
    for present, dimension in (
        (product_overlap, "product"),
        (buyer_overlap, "buyer"),
        (use_case_overlap, "use_case"),
        (commercial_substitution, "commercial_substitution"),
    ):
        if present:
            dimensions.append(dimension)
    if len(dimensions) == 4:
        classification = CompetitorClassification.DIRECT_COMPETITOR
        confidence = 0.9
    elif product_overlap and use_case_overlap:
        classification = CompetitorClassification.ADJACENT_VENDOR
        confidence = 0.68
    elif product_overlap:
        classification = (
            CompetitorClassification.POTENTIAL_BUYER_WITH_OVERLAPPING_FEATURES
        )
        confidence = 0.52
    elif any(
        term in lowered
        for term in ("customer support", "customer service", "customer success")
    ):
        classification = CompetitorClassification.NOT_COMPETITOR
        confidence = 0.55
    else:
        classification = CompetitorClassification.UNKNOWN
        confidence = 0.2
    return CompetitorAssessment(
        classification=classification,
        confidence=confidence,
        evidence_ids=evidence_ids,
        overlap_dimensions=tuple(dimensions),
    )


def _qualify_account(
    text: str,
    *,
    domain_validated: bool,
    size_in_range: bool | None,
    competitor_evidence_ids: tuple[str, ...] = (),
) -> tuple[str, list[str]]:
    lowered = text.lower()
    reasons: list[str] = []
    is_saas = any(
        term in lowered
        for term in (
            "b2b saas",
            "software as a service",
            "enterprise software",
            "cloud platform",
            "software platform",
            "saas platform",
            "cloud software",
            "software company",
        )
    )
    is_india = any(
        term in lowered
        for term in (
            "india",
            "bengaluru",
            "bangalore",
            "hyderabad",
            "pune",
            "mumbai",
            "gurugram",
            "gurgaon",
            "chennai",
            "noida",
        )
    )
    competitor = _competitor_assessment_from_text(
        text, evidence_ids=competitor_evidence_ids
    )
    has_support_operations = any(
        term in lowered
        for term in (
            "customer support",
            "customer success",
            "support team",
            "help center",
            "support portal",
            "technical support",
            "customer service",
        )
    )
    if domain_validated:
        reasons.append("Official-domain host matched the fetched canonical URL.")
    if is_saas:
        reasons.append("Source text supports a B2B or enterprise software model.")
    if is_india:
        reasons.append("Source text supports an India location or market connection.")
    if has_support_operations:
        reasons.append("Source text supports customer-support or success operations.")
    else:
        reasons.append("Customer-support operations remain unverified.")
    if size_in_range is True:
        reasons.append("Published employee evidence overlaps the 50-500 preference.")
    elif size_in_range is False:
        reasons.append("Published employee evidence falls outside 50-500.")
    else:
        reasons.append("Company size remains unknown.")
    evaluations = [
        CriterionEvaluation(
            "official_domain",
            CriterionRequirement.HARD,
            CriterionState.TRUE if domain_validated else CriterionState.UNKNOWN,
            reason=(
                "Official domain is validated."
                if domain_validated
                else "Official domain remains unverified."
            ),
        ),
        CriterionEvaluation(
            "b2b_software",
            CriterionRequirement.HARD,
            CriterionState.TRUE if is_saas else CriterionState.UNKNOWN,
            reason=(
                "B2B software model is source-supported."
                if is_saas
                else "B2B software model remains unknown."
            ),
        ),
        CriterionEvaluation(
            "india_connection",
            CriterionRequirement.HARD,
            CriterionState.TRUE if is_india else CriterionState.UNKNOWN,
            reason=(
                "India connection is source-supported."
                if is_india
                else "India connection remains unknown."
            ),
        ),
        CriterionEvaluation(
            "not_direct_competitor",
            CriterionRequirement.HARD,
            (
                CriterionState.FALSE
                if competitor.automatic_rejection_eligible
                else CriterionState.UNKNOWN
                if competitor.classification
                in {
                    CompetitorClassification.UNKNOWN,
                    CompetitorClassification.ADJACENT_VENDOR,
                    CompetitorClassification.POTENTIAL_BUYER_WITH_OVERLAPPING_FEATURES,
                }
                else CriterionState.TRUE
            ),
            reason=(
                "High-confidence direct support-automation competitor evidence found."
                if competitor.automatic_rejection_eligible
                else "Competitor overlap requires research; no automatic rejection."
                if competitor.classification
                in {
                    CompetitorClassification.UNKNOWN,
                    CompetitorClassification.ADJACENT_VENDOR,
                    CompetitorClassification.POTENTIAL_BUYER_WITH_OVERLAPPING_FEATURES,
                }
                else "No direct-competitor evidence found."
            ),
        ),
        CriterionEvaluation(
            "support_operations",
            CriterionRequirement.SOFT,
            CriterionState.TRUE
            if has_support_operations
            else CriterionState.UNKNOWN,
            reason=(
                "Support operations are source-supported."
                if has_support_operations
                else "Support operations remain unknown."
            ),
        ),
        CriterionEvaluation(
            "employee_preference",
            CriterionRequirement.SOFT,
            (
                CriterionState.TRUE
                if size_in_range is True
                else CriterionState.FALSE
                if size_in_range is False
                else CriterionState.UNKNOWN
            ),
            reason=(
                "Employee evidence overlaps the preferred range."
                if size_in_range is True
                else "Employee evidence is outside the preferred range."
                if size_in_range is False
                else "Employee count remains unknown; it is not treated as false."
            ),
        ),
    ]
    decision = decide_qualification(evaluations)
    return decision.status, [*reasons, *decision.reasons]


async def _research_account_sources(
    session: AsyncSession,
    run: ResearchRunRow,
    provider: LiveResearchProvider,
    *,
    company_name: str,
    domain: str,
    initial_source: SourceDocumentRow,
    initial_facts: list[EvidenceFactRow],
) -> tuple[list[SourceDocumentRow], list[EvidenceFactRow]]:
    sources = [initial_source]
    facts = list(initial_facts)
    plan = (
        (
            "OFFICIAL_DOMAIN_VALIDATION",
            (
                f"site:{domain} {company_name} about product customers careers "
                "customer success support news blog press"
            ),
            "account_research",
        ),
        (
            "ACCOUNT_SIGNAL_SUPPORT_HIRING",
            f'"{company_name}" hiring customer support OR customer success',
            "news",
        ),
        (
            "ACCOUNT_SIGNAL_EXPANSION",
            f'"{company_name}" expansion OR "opens office" OR "new market"',
            "news",
        ),
        (
            "ACCOUNT_SIGNAL_ENTERPRISE",
            f'"{company_name}" "enterprise customer" OR "customer growth"',
            "news",
        ),
        (
            "ACCOUNT_SIGNAL_LEADERSHIP",
            f'"{company_name}" appoints CRO OR "chief customer" OR "support leader"',
            "news",
        ),
        (
            "ACCOUNT_SIGNAL_FIRST_PARTY",
            f"site:{domain} careers support OR news expansion",
            "account_research",
        ),
    )
    seen_source_ids = {initial_source.id}
    for intent, query, purpose in plan:
        if run.searches_used >= settings.max_research_searches:
            break
        task = ResearchTaskRow(
            workspace_id=run.workspace_id,
            research_run_id=run.id,
            task_type=intent,
            query=query,
            status="running",
            source_strategy={"adapter": "search", "purpose": purpose, "limit": 5},
            result_summary={},
            error=None,
            started_at=_now(),
            completed_at=None,
        )
        session.add(task)
        run.searches_used += 1
        try:
            response = await provider.search(
                workspace_id=str(run.workspace_id),
                research_run_id=str(run.id),
                query=query,
                limit=5 if purpose != "news" else 3,
                freshness_days=730,
                purpose=purpose,
            )
            fetched = 0
            for result in response.results:
                if run.documents_used >= settings.max_research_documents:
                    break
                result_domain = _normalized_company_domain(str(result.url))
                if purpose != "news" and result_domain != domain:
                    continue
                if purpose == "news" and (
                    result_domain is None
                    or not _news_result_matches_company(
                        result,
                        company_name=company_name,
                        domain=domain,
                    )
                ):
                    continue
                try:
                    source_input = await provider.fetch(
                        workspace_id=str(run.workspace_id),
                        research_run_id=str(run.id),
                        url=str(result.url),
                    )
                except GatewayProviderError:
                    continue
                source, new_facts = await _persist_source(
                    session,
                    run,
                    source_input,
                    f"{company_name} {query} {result.title}",
                )
                if source.id in seen_source_ids:
                    continue
                seen_source_ids.add(source.id)
                sources.append(source)
                facts.extend(new_facts)
                run.documents_used += 1
                fetched += 1
                if fetched >= (3 if purpose != "news" else 2):
                    break
            task.status = "completed"
            task.result_summary = {
                "results": len(response.results),
                "documents": fetched,
                "backend": response.backend,
            }
        except GatewayProviderError as exc:
            task.status = "failed"
            task.error = _error_payload(exc)
        task.completed_at = _now()
        await session.flush()
    return sources, facts


GATEWAY_CODE_TO_OUTCOME: dict[str, RetrievalOutcome] = {
    "SOURCE_NOT_FOUND": RetrievalOutcome.NOT_FOUND,
    "SOURCE_FORBIDDEN": RetrievalOutcome.FORBIDDEN,
    "SOURCE_UNAVAILABLE": RetrievalOutcome.UNAVAILABLE,
    "FETCH_TIMEOUT": RetrievalOutcome.TIMED_OUT,
    "RATE_LIMITED": RetrievalOutcome.RATE_LIMITED,
    "URL_POLICY_BLOCKED": RetrievalOutcome.BLOCKED_BY_POLICY,
    "UNSUPPORTED_CONTENT_TYPE": RetrievalOutcome.UNSUPPORTED_CONTENT,
}


def _retrieval_outcome_for(code: str) -> RetrievalOutcome:
    """Preserve the gateway's distinction instead of collapsing it to one error."""

    return GATEWAY_CODE_TO_OUTCOME.get(code, RetrievalOutcome.UNAVAILABLE)


async def _fetch_supplied_official_sources(
    session: AsyncSession,
    run: ResearchRunRow,
    provider: LiveResearchProvider,
    *,
    company_name: str,
    domain: str,
) -> tuple[list[SourceDocumentRow], list[EvidenceFactRow], RetrievalSummary]:
    sources: list[SourceDocumentRow] = []
    facts: list[EvidenceFactRow] = []
    attempts: list[RetrievalAttempt] = []
    seen_source_ids: set[uuid.UUID] = set()
    paths = (
        "",
        "about",
        "product",
        "products",
        "customers",
        "careers",
        "blog",
        "news",
    )[: settings.max_pages_per_account]
    for path in paths:
        if run.documents_used >= settings.max_research_documents:
            break
        url = f"https://{domain}/" + (path if path else "")
        task = ResearchTaskRow(
            workspace_id=run.workspace_id,
            research_run_id=run.id,
            task_type="BYOA_OFFICIAL_URL_FETCH",
            query=url,
            status="running",
            source_strategy={
                "adapter": "fetch",
                "purpose": "byoa_official_research",
                "search_provider_required": False,
            },
            result_summary={},
            error=None,
            started_at=_now(),
            completed_at=None,
        )
        session.add(task)
        try:
            source_input = await provider.fetch(
                workspace_id=str(run.workspace_id),
                research_run_id=str(run.id),
                url=url,
            )
            canonical_source_domain = _normalized_company_domain(
                str(source_input.canonical_url)
            )
            if canonical_source_domain != domain:
                task.status = "failed"
                task.error = {
                    "category": "CROSS_DOMAIN_REDIRECT_REJECTED",
                    "message": (
                        "Official URL redirected to a different registrable domain"
                    ),
                    "retryable": False,
                }
                attempts.append(
                    RetrievalAttempt(
                        url=url,
                        outcome=RetrievalOutcome.CROSS_DOMAIN_REDIRECT,
                        detail=(
                            f"Redirected to {canonical_source_domain}, "
                            f"which is not {domain}"
                        ),
                    )
                )
            else:
                source, new_facts = await _persist_source(
                    session,
                    run,
                    source_input,
                    f"{company_name} official company facts",
                )
                if source.id not in seen_source_ids:
                    seen_source_ids.add(source.id)
                    sources.append(source)
                    facts.extend(new_facts)
                    run.documents_used += 1
                task.status = "completed"
                task.result_summary = {
                    "documents": 1,
                    "facts": len(new_facts),
                    "canonical_domain": canonical_source_domain,
                }
                truncated = bool(source_input.metadata.get("truncated"))
                attempts.append(
                    RetrievalAttempt(
                        url=url,
                        outcome=(
                            RetrievalOutcome.TRUNCATED
                            if truncated
                            else RetrievalOutcome.RETRIEVED
                        ),
                        detail=(
                            "Page exceeded the size limit and was read only in part"
                            if truncated
                            else None
                        ),
                    )
                )
        except GatewayProviderError as exc:
            task.status = "failed"
            task.error = _error_payload(exc)
            attempts.append(
                RetrievalAttempt(
                    url=url,
                    outcome=_retrieval_outcome_for(exc.category),
                    detail=exc.safe_message,
                )
            )
        task.completed_at = _now()
        await session.flush()
    # A truncated page still yielded evidence, so it counts as retrieved.
    retrieved = sum(
        1
        for item in attempts
        if item.outcome
        in {RetrievalOutcome.RETRIEVED, RetrievalOutcome.TRUNCATED}
    )
    summary = RetrievalSummary(
        attempted=len(attempts), retrieved=retrieved, attempts=attempts
    )
    return sources, facts, summary


async def discover_accounts(
    icp_id: str, provider: LiveResearchProvider | None = None
) -> None:
    production_provider = provider is None
    provider = provider or LiveResearchProvider()
    async with SessionFactory() as session:
        icp = await session.get(ICPProfileRow, uuid.UUID(icp_id))
        if icp is None or icp.selected_at is None:
            return
        run = await session.get(ResearchRunRow, icp.research_run_id)
        if run is None:
            return
        if production_provider and not search_provider_configured():
            run.status = "failed"
            run.current_stage = "configuration_required"
            run.error = {
                "category": "CONFIGURATION_REQUIRED",
                "message": (
                    "Account research is available. Automatic account discovery "
                    "requires a configured search provider."
                ),
                "retryable": True,
            }
            run.updated_at = _now()
            await session.commit()
            return
        product = await session.get(ProductProfileRow, run.product_id)
        if product is None:
            await _fail_run(session, run, "PRODUCT_NOT_FOUND", "Product was removed")
            return
        run.status = "discovering_accounts"
        run.current_stage = "account_discovery"
        await session.commit()
        queries = [
            "India cybersecurity SaaS companies official websites",
            "India B2B SaaS customer onboarding companies official websites",
            "India compliance SaaS companies official websites",
            "India SaaS spend management companies official websites",
            "India revenue intelligence SaaS companies official websites",
            "India product analytics SaaS companies official websites",
            "India HR SaaS companies official websites",
            "India logistics SaaS companies official websites",
            "India developer tools SaaS companies official websites",
            "Bengaluru B2B SaaS enterprise software official company website",
            "Mumbai B2B cloud software official company website",
            "Pune enterprise SaaS platform official company website",
            "Gurugram B2B SaaS official company website",
            "India ecommerce SaaS platform official company website",
            "India fintech SaaS platform official company website",
        ]
        workflow_started = monotonic()
        candidates: dict[str, DiscoveryCandidate] = {}
        target_terms = _tokens(
            f"{product.target_market} {icp.name} {icp.description}"
        )
        discovery_diagnostics = {
            "search_results": 0,
            "candidate_pages": 0,
            "prequalified_candidates": 0,
            "provider_fallbacks": 0,
            "fetch_failures": 0,
            "no_evidence": 0,
            "preliminary_research_required": 0,
            "final_rejections": 0,
        }
        for query in queries:
            if monotonic() - workflow_started >= settings.max_elapsed_seconds:
                break
            if len(candidates) >= settings.max_account_candidates:
                break
            try:
                response = await provider.search(
                    workspace_id=str(run.workspace_id),
                    research_run_id=str(run.id),
                    query=query,
                    limit=min(8, settings.max_account_candidates),
                    purpose="account_discovery",
                )
                run.searches_used += 1
                discovery_diagnostics["search_results"] += len(response.results)
                if (
                    response.diagnostics is not None
                    and response.diagnostics.fallback_used
                ):
                    discovery_diagnostics["provider_fallbacks"] += 1
                for item in response.results:
                    identity = resolve_company_identity(str(item.url))
                    domain = identity.canonical_company_domain
                    if (
                        not domain
                        or not _is_candidate_company_page(item)
                        or identity.confidence < 0.75
                    ):
                        continue
                    candidate = candidates.get(domain)
                    if candidate is None:
                        candidate = DiscoveryCandidate(
                            result=item,
                            identity=identity,
                            queries=set(),
                            providers=set(),
                        )
                        candidates[domain] = candidate
                    candidate.queries.add(query)
                    candidate.providers.add(item.provider or item.backend)
                discovery_diagnostics["candidate_pages"] = len(candidates)
            except GatewayProviderError:
                continue
        for domain, candidate in candidates.items():
            score_breakdown = candidate_relevance_breakdown(
                title=candidate.result.title,
                snippet=candidate.result.snippet,
                target_terms=target_terms,
                official_page=True,
                provider_score=candidate.result.provider_relevance_score,
                query_hits=len(candidate.queries),
                provider_hits=len(candidate.providers),
            )
            candidate.score = score_breakdown.total
            candidate.score_diagnostics = {
                "term_coverage": score_breakdown.term_coverage,
                "term_coverage_points": score_breakdown.term_coverage_points,
                "official_page_points": score_breakdown.official_page_points,
                "provider_relevance_points": (
                    score_breakdown.provider_relevance_points
                ),
                "query_agreement_points": score_breakdown.query_agreement_points,
                "provider_agreement_points": (
                    score_breakdown.provider_agreement_points
                ),
            }
            candidate.prequalification = evaluate_prequalification(
                _discovery_prequalification_input(candidate),
                high_threshold=(
                    settings.candidate_prequalification_high_threshold
                ),
                middle_threshold=(
                    settings.candidate_prequalification_middle_threshold
                ),
                low_threshold=settings.candidate_prequalification_low_threshold,
            )
            stage = candidate.prequalification.outcome.value
            session.add(
                ResearchCandidateRow(
                    workspace_id=run.workspace_id,
                    research_run_id=run.id,
                    discovered_url=str(candidate.result.url),
                    hostname=candidate.identity.hostname,
                    registrable_domain=domain,
                    canonical_company_domain=domain,
                    page_role=candidate.identity.page_role.value,
                    candidate_score=candidate.score,
                    stage=stage,
                    query_provenance=sorted(candidate.queries),
                    provider_provenance=sorted(candidate.providers),
                    diagnostics={
                        "domain_confidence": candidate.identity.confidence,
                        "provider_relevance_score": (
                            candidate.result.provider_relevance_score
                        ),
                        "evidence_stage": EvidenceStage.DISCOVERY_HINT.value,
                        "candidate_relevance": candidate.score,
                        "identity_confidence": candidate.identity.confidence,
                        "evidence_coverage": 0,
                        "research_worthiness": (
                            candidate.prequalification.research_worthiness
                        ),
                        "prequalification_outcome": (
                            candidate.prequalification.outcome.value
                        ),
                        "score_contributions": candidate.score_diagnostics,
                        "research_requirements": list(
                            candidate.prequalification.research_requirements
                        ),
                        "rejection_reasons": list(
                            candidate.prequalification.rejection_reasons
                        ),
                        "thresholds": {
                            "high": candidate.prequalification.high_threshold,
                            "middle": candidate.prequalification.middle_threshold,
                            "low": candidate.prequalification.low_threshold,
                        },
                    },
                )
            )
        await session.commit()
        shortlisted = sorted(
            (
                (domain, candidate)
                for domain, candidate in candidates.items()
                if candidate.prequalification is not None
                and candidate.prequalification.outcome
                in {
                    PrequalificationOutcome.PREQUALIFIED,
                    PrequalificationOutcome.PREQUALIFIED_WITH_UNCERTAINTY,
                }
            ),
            key=lambda item: (
                item[1].prequalification.research_worthiness
                if item[1].prequalification is not None
                else 0,
                item[1].score,
            ),
            reverse=True,
        )
        discovery_diagnostics["prequalified_candidates"] = len(shortlisted)
        created = 0
        for domain, candidate in shortlisted:
            result = candidate.result
            if monotonic() - workflow_started >= settings.max_elapsed_seconds:
                break
            if created >= settings.max_accounts_researched:
                break
            try:
                source_input = await provider.fetch(
                    workspace_id=str(run.workspace_id),
                    research_run_id=str(run.id),
                    url=str(result.url),
                )
            except GatewayProviderError:
                discovery_diagnostics["fetch_failures"] += 1
                continue
            source, facts = await _persist_source(
                session,
                run,
                source_input,
                f"{product.target_market} {result.title} {domain}",
            )
            if not facts:
                discovery_diagnostics["no_evidence"] += 1
                continue
            canonical_domain = _normalized_company_domain(source.canonical_url)
            domain_validated = canonical_domain == domain
            preliminary_text = source.cleaned_text
            _, _, preliminary_size_in_range = _company_size_from_text(preliminary_text)
            candidate_row = await session.scalar(
                select(ResearchCandidateRow).where(
                    ResearchCandidateRow.research_run_id == run.id,
                    ResearchCandidateRow.registrable_domain == domain,
                )
            )
            if candidate_row is not None:
                candidate_row.diagnostics = {
                    **candidate_row.diagnostics,
                    "evidence_stage": EvidenceStage.PREQUALIFICATION_EVIDENCE.value,
                    "evidence_coverage": round(min(1.0, len(facts) / 4), 4),
                }
            preliminary_qualification, _ = _qualify_account(
                preliminary_text,
                domain_validated=domain_validated,
                size_in_range=preliminary_size_in_range,
            )
            if preliminary_qualification == "INSUFFICIENT_EVIDENCE":
                discovery_diagnostics["preliminary_research_required"] += 1
                if candidate_row is not None:
                    candidate_row.stage = (
                        PrequalificationOutcome.PREQUALIFIED_WITH_UNCERTAINTY.value
                    )
                    candidate_row.diagnostics = {
                        **candidate_row.diagnostics,
                        "preliminary_qualification": (
                            "INSUFFICIENT_EVIDENCE_RESEARCH_CONTINUES"
                        ),
                    }
            sources, facts = await _research_account_sources(
                session,
                run,
                provider,
                company_name=_account_name(source.title, domain),
                domain=domain,
                initial_source=source,
                initial_facts=facts,
            )
            official_sources = [
                item
                for item in sources
                if _normalized_company_domain(item.canonical_url) == domain
            ]
            combined_text = " ".join(
                item.cleaned_text for item in official_sources
            )
            employee_band, size_status, size_in_range = _company_size_from_text(
                combined_text
            )
            official_source_ids = {item.id for item in official_sources}
            official_fact_ids = tuple(
                str(item.id) for item in facts if item.source_id in official_source_ids
            )
            qualification, qualification_reasons = _qualify_account(
                combined_text,
                domain_validated=domain_validated,
                size_in_range=size_in_range,
                competitor_evidence_ids=official_fact_ids,
            )
            if qualification == "INSUFFICIENT_EVIDENCE":
                discovery_diagnostics["final_rejections"] += 1
                candidate_row = await session.scalar(
                    select(ResearchCandidateRow).where(
                        ResearchCandidateRow.research_run_id == run.id,
                        ResearchCandidateRow.registrable_domain == domain,
                    )
                )
                if candidate_row is not None:
                    candidate_row.stage = "REJECTED_QUALIFICATION"
                continue
            firmographics = await PublicEvidenceFirmographicProvider().enrich(
                company_name=_account_name(source.title, domain),
                domain=domain,
                public_text=combined_text,
                source_ids=tuple(str(item.id) for item in official_sources),
            )
            qualification_coverage = (
                1.0 if qualification == "QUALIFIED" else 0.75
            )
            competitor_assessment = _competitor_assessment_from_text(
                combined_text,
                evidence_ids=official_fact_ids,
            )
            candidate_row = await session.scalar(
                select(ResearchCandidateRow).where(
                    ResearchCandidateRow.research_run_id == run.id,
                    ResearchCandidateRow.registrable_domain == domain,
                )
            )
            if candidate_row is not None:
                candidate_row.diagnostics = {
                    **candidate_row.diagnostics,
                    "evidence_stage": EvidenceStage.VERIFIED_ACCOUNT_EVIDENCE.value,
                    "evidence_coverage": round(
                        min(1.0, len(official_fact_ids) / 4), 4
                    ),
                    "competitor": {
                        "classification": (
                            competitor_assessment.classification.value
                        ),
                        "confidence": competitor_assessment.confidence,
                        "evidence_ids": list(competitor_assessment.evidence_ids),
                        "overlap_dimensions": list(
                            competitor_assessment.overlap_dimensions
                        ),
                        "automatic_rejection_eligible": (
                            competitor_assessment.automatic_rejection_eligible
                        ),
                    },
                }
            firmographic_payload = {
                "provider": firmographics.provider,
                "employee_count": {
                    "value": firmographics.employee_count.value,
                    "precision": firmographics.employee_count.precision.value,
                    "confidence": firmographics.employee_count.confidence,
                    "source_ids": list(firmographics.employee_count.source_ids),
                    "rationale": firmographics.employee_count.rationale,
                },
                "geography": {
                    "value": firmographics.geography.value,
                    "precision": firmographics.geography.precision.value,
                    "confidence": firmographics.geography.confidence,
                    "source_ids": list(firmographics.geography.source_ids),
                },
                "business_model": {
                    "value": firmographics.business_model.value,
                    "precision": firmographics.business_model.precision.value,
                    "confidence": firmographics.business_model.confidence,
                    "source_ids": list(firmographics.business_model.source_ids),
                },
                "industry": {
                    "value": firmographics.industry.value,
                    "precision": firmographics.industry.precision.value,
                    "confidence": firmographics.industry.confidence,
                    "source_ids": list(firmographics.industry.source_ids),
                },
            }
            lowered_text = combined_text.lower()
            industry = (
                "B2B SaaS"
                if any(
                    term in lowered_text
                    for term in (
                        "b2b saas",
                        "enterprise software",
                        "software as a service",
                    )
                )
                else None
            )
            location = (
                "India"
                if any(
                    term in lowered_text
                    for term in (
                        "india",
                        "bengaluru",
                        "bangalore",
                        "hyderabad",
                        "pune",
                        "mumbai",
                        "gurugram",
                        "chennai",
                    )
                )
                else None
            )
            account = await session.scalar(
                select(AccountRow).where(
                    AccountRow.workspace_id == run.workspace_id,
                    AccountRow.domain == domain,
                )
            )
            if account is None:
                account = AccountRow(
                    workspace_id=run.workspace_id,
                    icp_id=None,
                    icp_profile_id=icp.id,
                    name=_account_name(source.title, domain),
                    domain=domain,
                    description=facts[0].claim,
                    industry=industry,
                    location=location,
                    employee_band=employee_band,
                    business_model=None,
                    attributes={
                        "product_mode": "AUTONOMOUS_DISCOVERY_EXPERIMENTAL",
                        "provenance": "DISCOVERED",
                        "review_status": "PENDING",
                        "qualification_status": qualification,
                        "qualification_reasons": qualification_reasons,
                        "company_size_status": size_status,
                        "company_size_in_range": size_in_range is True,
                        "discovery_source": str(result.url),
                        "registrable_domain": domain,
                        "official_subdomains": list(
                            candidate.identity.official_subdomains
                        ),
                        "domain_confidence": candidate.identity.confidence,
                        "candidate_relevance_score": candidate.score,
                        "query_provenance": sorted(candidate.queries),
                        "provider_provenance": sorted(candidate.providers),
                        "qualification_coverage": qualification_coverage,
                        "firmographics": firmographic_payload,
                        "competitor": {
                            "classification": (
                                competitor_assessment.classification.value
                            ),
                            "confidence": competitor_assessment.confidence,
                            "evidence_ids": list(
                                competitor_assessment.evidence_ids
                            ),
                            "overlap_dimensions": list(
                                competitor_assessment.overlap_dimensions
                            ),
                            "automatic_rejection_eligible": (
                                competitor_assessment.automatic_rejection_eligible
                            ),
                        },
                        "domain_validation": (
                            "VALIDATED" if domain_validated else "MISMATCH"
                        ),
                        "source_ids": [str(item.id) for item in sources],
                    },
                    evidence_ids=[str(item.id) for item in facts],
                    last_researched_at=_now(),
                )
                session.add(account)
                await session.flush()
            else:
                account.icp_profile_id = icp.id
                account.description = facts[0].claim
                account.evidence_ids = [str(item.id) for item in facts]
                account.last_researched_at = _now()
                account.industry = industry
                account.location = location
                account.employee_band = employee_band
                account.attributes = {
                    **account.attributes,
                    "product_mode": "AUTONOMOUS_DISCOVERY_EXPERIMENTAL",
                    "provenance": "DISCOVERED",
                    "qualification_status": qualification,
                    "qualification_reasons": qualification_reasons,
                    "company_size_status": size_status,
                    "company_size_in_range": size_in_range is True,
                    "discovery_source": str(result.url),
                    "registrable_domain": domain,
                    "official_subdomains": list(
                        candidate.identity.official_subdomains
                    ),
                    "domain_confidence": candidate.identity.confidence,
                    "candidate_relevance_score": candidate.score,
                    "query_provenance": sorted(candidate.queries),
                    "provider_provenance": sorted(candidate.providers),
                    "qualification_coverage": qualification_coverage,
                    "competitor": {
                        "classification": competitor_assessment.classification.value,
                        "confidence": competitor_assessment.confidence,
                        "evidence_ids": list(competitor_assessment.evidence_ids),
                        "overlap_dimensions": list(
                            competitor_assessment.overlap_dimensions
                        ),
                        "automatic_rejection_eligible": (
                            competitor_assessment.automatic_rejection_eligible
                        ),
                    },
                    "firmographics": firmographic_payload,
                    "domain_validation": (
                        "VALIDATED" if domain_validated else "MISMATCH"
                    ),
                    "source_ids": [str(item.id) for item in sources],
                }
            await _score_and_brief(session, run, product, icp, account, source, facts)
            candidate_row = await session.scalar(
                select(ResearchCandidateRow).where(
                    ResearchCandidateRow.research_run_id == run.id,
                    ResearchCandidateRow.registrable_domain == domain,
                )
            )
            if candidate_row is not None:
                candidate_row.stage = "ACCEPTED"
            created += 1
            run.documents_used += 1
            await session.commit()
        run.status = "completed" if created else "partial"
        run.current_stage = "completed" if created else "account_discovery_partial"
        run.completed_at = _now()
        run.updated_at = _now()
        if not created:
            run.error = {
                "category": "NO_ACCOUNT_EVIDENCE",
                "message": "No researchable account candidates produced evidence",
                "details": discovery_diagnostics,
            }
        await session.commit()


def _domain_brand(domain: str) -> str:
    domain_parts = domain.split(".")
    country_suffixes = {
        ("co", "in"),
        ("co", "uk"),
        ("com", "au"),
        ("com", "br"),
        ("co", "jp"),
    }
    label_index = -3 if tuple(domain_parts[-2:]) in country_suffixes else -2
    return (
        domain_parts[label_index] if len(domain_parts) >= abs(label_index) else domain_parts[0]
    ).replace("-", " ")


def _account_name(title: str, domain: str) -> str:
    for separator in (" | ", " — ", " - ", " – "):
        if separator in title:
            title = title.split(separator, 1)[0]
            break
    clean = " ".join(title.split()).strip()
    domain_label = _domain_brand(domain)
    normalized_title = re.sub(r"[^a-z0-9]", "", clean.lower())
    normalized_domain = re.sub(r"[^a-z0-9]", "", domain_label.lower())
    if normalized_domain and normalized_domain not in normalized_title:
        clean = domain_label.title()
    return (clean or domain.split(".")[0].replace("-", " ").title())[:180]


def _news_result_matches_company(
    result: SearchResult,
    *,
    company_name: str,
    domain: str,
) -> bool:
    """Require a specific entity token before external news becomes evidence."""
    result_domain = _normalized_company_domain(str(result.canonical_url or result.url))
    target_domain = _normalized_company_domain(
        domain if "://" in domain else f"https://{domain}"
    )
    if (
        result_domain
        and target_domain
        and result_domain != target_domain
        and _domain_brand(result_domain) == _domain_brand(target_domain)
    ):
        return False
    haystack = f"{result.title} {result.snippet}".lower()
    brand = _domain_brand(domain).lower()
    if len(brand) >= 4 and re.search(
        rf"(?<![a-z0-9]){re.escape(brand)}(?![a-z0-9])", haystack
    ):
        return True
    company = re.sub(r"\s+", " ", company_name.lower()).strip()
    return len(company) >= 4 and re.search(
        rf"(?<![a-z0-9]){re.escape(company)}(?![a-z0-9])", haystack
    ) is not None


def _identity_record_for_account(account: AccountRow) -> CompanyIdentityRecord:
    raw = account.attributes.get("company_identity")
    aliases: list[VerifiedAlias] = []
    relationships: list[VerifiedEntityRelationship] = []
    if isinstance(raw, dict):
        for item in raw.get("known_aliases", []):
            if not isinstance(item, dict):
                continue
            evidence_ids = tuple(
                str(value) for value in item.get("evidence_ids", []) if value
            )
            if item.get("name") and evidence_ids:
                aliases.append(
                    VerifiedAlias(str(item["name"]), evidence_ids)
                )
        for item in raw.get("relationships", []):
            if not isinstance(item, dict):
                continue
            try:
                relation = EntityRelation(str(item.get("relation")))
            except ValueError:
                continue
            evidence_ids = tuple(
                str(value) for value in item.get("evidence_ids", []) if value
            )
            if item.get("subject_domain") and item.get("object_domain"):
                relationships.append(
                    VerifiedEntityRelationship(
                        subject_domain=str(item["subject_domain"]),
                        object_domain=str(item["object_domain"]),
                        relation=relation,
                        evidence_ids=evidence_ids,
                    )
                )
    official_domains = {
        account.domain,
        *(
            str(value)
            for value in (
                raw.get("verified_official_domains", [])
                if isinstance(raw, dict)
                else []
            )
            if value
        ),
    }
    warnings = tuple(
        str(value)
        for value in (
            raw.get("unresolved_identity_warnings", [])
            if isinstance(raw, dict)
            else []
        )
        if value
    )
    # Import records a pending marker because the supplied domain has not been
    # checked yet. Once research verifies that domain the marker is stale, and
    # leaving it in place pinned every BYOA account to IDENTITY_REVIEW_REQUIRED
    # forever -- no imported account could ever reach another state.
    #
    # The signal is `domain_validation`, which research sets to VALIDATED only
    # after a fetch whose post-redirect canonical domain still matched.
    # `official_domains` always contains the account's own domain, so testing
    # membership there would clear the marker unconditionally.
    if str(account.attributes.get("domain_validation") or "") == "VALIDATED":
        warnings = tuple(
            warning
            for warning in warnings
            if warning != IMPORT_PENDING_IDENTITY_WARNING
        )
    return CompanyIdentityRecord(
        canonical_company_name=(
            str(raw.get("canonical_company_name"))
            if isinstance(raw, dict) and raw.get("canonical_company_name")
            else account.name
        ),
        canonical_registrable_domain=account.domain,
        verified_official_domains=tuple(sorted(official_domains)),
        known_aliases=tuple(aliases),
        legal_name=(
            str(raw["legal_name"])
            if isinstance(raw, dict) and raw.get("legal_name")
            else None
        ),
        product_names=(),
        product_domains=tuple(
            str(value)
            for value in (
                raw.get("product_domains", [])
                if isinstance(raw, dict)
                else []
            )
            if value
        ),
        parent_organization=(
            str(raw["parent_organization"])
            if isinstance(raw, dict) and raw.get("parent_organization")
            else None
        ),
        subsidiaries=tuple(
            str(value)
            for value in (
                raw.get("subsidiaries", [])
                if isinstance(raw, dict)
                else []
            )
            if value
        ),
        relationships=tuple(relationships),
        relationship_evidence_ids=tuple(
            str(value)
            for relationship in relationships
            for value in relationship.evidence_ids
        ),
        identity_confidence=float(
            str(account.attributes.get("domain_confidence") or 0)
        ),
        unresolved_identity_warnings=warnings,
    )


def _assess_account_evidence(
    account: AccountRow,
    facts: list[EvidenceFactRow],
    source_by_id: dict[uuid.UUID, SourceDocumentRow],
) -> tuple[
    CompanyIdentityRecord,
    list[EvidenceFactRow],
    dict[uuid.UUID, EvidenceAttachmentAssessment],
    list[dict[str, object]],
]:
    identity = _identity_record_for_account(account)
    conflicting_entities = tuple(
        _account_name(
            item.title,
            _normalized_company_domain(item.canonical_url) or "",
        )
        for item in source_by_id.values()
        if str(item.provenance.get("source_role") or "") == SourceRole.FIRST_PARTY
        and _normalized_company_domain(item.canonical_url)
        not in identity.verified_official_domains
    )
    attached: list[EvidenceFactRow] = []
    assessments: dict[uuid.UUID, EvidenceAttachmentAssessment] = {}
    rejected: list[dict[str, object]] = []
    unresolved_identity_conflict = False
    for fact in facts:
        source = source_by_id.get(fact.source_id)
        if source is None:
            continue
        current_page_role = classify_result_page(source.canonical_url)
        current_source_role = {
            ResultPageRole.OFFICIAL_ROOT: SourceRole.FIRST_PARTY,
            ResultPageRole.OFFICIAL_SUBDOMAIN: SourceRole.FIRST_PARTY,
            ResultPageRole.DIRECTORY: SourceRole.DIRECTORY,
            ResultPageRole.NEWS: SourceRole.NEWS,
            ResultPageRole.SOCIAL: SourceRole.COMMUNITY,
            ResultPageRole.VENDOR_MARKETING: SourceRole.VENDOR_MARKETING,
            ResultPageRole.OTHER: SourceRole.OTHER,
        }[current_page_role]
        persisted_source_role = str(
            source.provenance.get("source_role") or SourceRole.OTHER.value
        )
        source_role = (
            current_source_role.value
            if current_source_role
            in {
                SourceRole.DIRECTORY,
                SourceRole.NEWS,
                SourceRole.COMMUNITY,
            }
            else persisted_source_role
        )
        assessment = assess_evidence_attachment(
            identity,
            source_url=source.canonical_url,
            source_role=source_role,
            source_title=source.title,
            passage=fact.passage,
            subject_entity=fact.subject,
            claim_scope=None,
            conflicting_entities=conflicting_entities,
        )
        assessments[fact.id] = assessment
        if assessment.decision == AttachmentDecision.ATTACHED:
            attached.append(fact)
        else:
            source_brand = (
                re.sub(r"[^a-z0-9]", "", _domain_brand(assessment.source_domain))
                if assessment.source_domain
                else ""
            )
            account_brand = re.sub(
                r"[^a-z0-9]", "", _domain_brand(account.domain)
            )
            unresolved_identity_conflict = (
                unresolved_identity_conflict
                or assessment.decision == AttachmentDecision.RELATED_ENTITY_ONLY
                or (
                    len(source_brand) >= 4
                    and len(account_brand) >= 4
                    and (
                        source_brand.startswith(account_brand)
                        or account_brand.startswith(source_brand)
                    )
                )
            )
            rejected.append(
                {
                    "evidence_id": str(fact.id),
                    "source_id": str(fact.source_id),
                    "source_domain": assessment.source_domain,
                    "source_url": source.canonical_url,
                    # The passage is what lets a reader judge the exclusion for
                    # themselves; without it the panel is an unfalsifiable claim.
                    "passage": fact.passage[:400],
                    "subject": assessment.subject_entity,
                    "relation": assessment.relation.value,
                    "scope": assessment.claim_scope.value,
                    "decision": assessment.decision.value,
                    "reason": assessment.reason,
                }
            )
    if unresolved_identity_conflict:
        identity = CompanyIdentityRecord(
            **{
                **identity.__dict__,
                "unresolved_identity_warnings": tuple(
                    sorted(
                        {
                            *identity.unresolved_identity_warnings,
                            "One or more sources may belong to another entity.",
                        }
                    )
                ),
            }
        )
    return identity, attached, assessments, rejected


EVENT_PAGE_MARKERS = (
    "/careers",
    "/jobs",
    "/news",
    "/blog",
    "/press",
    "/announcements",
)


def signal_event_date(source: SourceDocumentRow | None) -> datetime | None:
    """Return the date the event actually happened, or None when it is unknown.

    `EvidenceFactRow.observed_at` falls back to retrieval time, so it must never be
    used as an event date: an undated page would otherwise look maximally fresh.
    """

    return source.published_at if source is not None else None


def _is_event_semantics_page(source: SourceDocumentRow) -> bool:
    """Pages that report happenings rather than describe the company in general."""

    return any(marker in source.url.lower() for marker in EVENT_PAGE_MARKERS)


def _signals_from_facts(
    facts: list[EvidenceFactRow],
    source_by_id: dict[uuid.UUID, SourceDocumentRow] | None = None,
    *,
    company_name: str | None = None,
    domain: str | None = None,
    attachment_by_fact_id: (
        dict[uuid.UUID, EvidenceAttachmentAssessment] | None
    ) = None,
) -> list[tuple[str, EvidenceFactRow, datetime | None]]:
    matches: list[tuple[str, EvidenceFactRow, datetime | None]] = []
    seen: set[tuple[str, uuid.UUID]] = set()
    for fact in facts:
        assessment = (
            attachment_by_fact_id.get(fact.id)
            if attachment_by_fact_id is not None
            else None
        )
        if assessment is not None and (
            assessment.decision != AttachmentDecision.ATTACHED
            or assessment.claim_scope
            in {ClaimScope.MARKET_LEVEL, ClaimScope.PARTNER_LEVEL}
        ):
            continue
        lowered = fact.claim.lower()
        for signal_type, term_groups in SIGNAL_RULES.items():
            if not all(any(term in lowered for term in group) for group in term_groups):
                continue
            source = source_by_id.get(fact.source_id) if source_by_id else None
            if source is not None:
                source_role = str(
                    source.provenance.get("source_role") or SourceRole.OTHER.value
                )
                if source_role == SourceRole.VENDOR_MARKETING.value:
                    continue
                source_domain = _normalized_company_domain(source.canonical_url)
                first_party = bool(domain and source_domain == domain)
                if (
                    company_name
                    and domain
                    and not first_party
                    and not _news_result_matches_company(
                        SearchResult.model_validate(
                            {
                                "url": source.url,
                                "canonical_url": source.canonical_url,
                                "title": source.title,
                                "snippet": fact.passage,
                                "backend": source.backend,
                            }
                        ),
                        company_name=company_name,
                        domain=domain,
                    )
                ):
                    continue
            # Event semantics are required of every signal type without exception. A
            # static page describing the company in general terms ("trusted by 100+
            # customers") is not evidence that anything is happening now.
            event_date = signal_event_date(source)
            if source is not None and event_date is None:
                if not _is_event_semantics_page(source):
                    continue
            if event_date is not None and (_now() - event_date).days > 730:
                continue
            key = (signal_type, fact.id)
            if key not in seen:
                matches.append((signal_type, fact, event_date))
                seen.add(key)
    return matches


async def _score_and_brief(
    session: AsyncSession,
    run: ResearchRunRow,
    product: ProductProfileRow,
    icp: ICPProfileRow,
    account: AccountRow,
    source: SourceDocumentRow,
    facts: list[EvidenceFactRow],
) -> None:
    source_ids = list(dict.fromkeys(item.source_id for item in facts))
    all_source_rows = list(
        (
            await session.scalars(
                select(SourceDocumentRow)
                .where(SourceDocumentRow.id.in_(source_ids))
                .order_by(SourceDocumentRow.created_at)
            )
        ).all()
    )
    all_source_by_id = {item.id: item for item in all_source_rows}
    (
        identity_record,
        attached_facts,
        attachment_by_fact_id,
        rejected_evidence,
    ) = _assess_account_evidence(account, facts, all_source_by_id)
    if not attached_facts:
        raise ValueError("No entity-compatible account evidence remains")
    facts = attached_facts
    attached_source_ids = {item.source_id for item in facts}
    source_rows = [
        item for item in all_source_rows if item.id in attached_source_ids
    ]
    source_by_id = {item.id: item for item in source_rows}
    raw_retrieval = account.attributes.get("retrieval")
    retrieval_summary = (
        RetrievalSummary.model_validate(raw_retrieval)
        if isinstance(raw_retrieval, dict)
        else RetrievalSummary()
    )
    target_tokens = _tokens(product.target_market)
    evidence_tokens = _tokens(" ".join(item.claim for item in facts))
    overlap = len(target_tokens & evidence_tokens) / max(1, len(target_tokens))
    signal_matches = _signals_from_facts(
        facts,
        source_by_id,
        company_name=account.name,
        domain=account.domain,
        attachment_by_fact_id=attachment_by_fact_id,
    )
    signal_match = signal_matches[0] if signal_matches else None
    signal_evidence = [str(item[1].id) for item in signal_matches]
    fit_evidence = [str(facts[0].id)]
    top_signal_event_date = signal_match[2] if signal_match else None
    signal_strength = (
        min(100.0, 62.0 + len(signal_matches) * 8) if signal_match else 0.0
    )
    all_text = " ".join(item.claim for item in facts).lower()
    # None means "no evidence either way". Scoring absence as 0 would treat unknown
    # as a verified mismatch, which is exactly what the product principles forbid --
    # and it dragged Fit to 0 for every real company whose pages simply do not
    # state their industry or location.
    industry_match: float | None
    if any(term in all_text for term in ("b2b saas", "enterprise software")):
        industry_match = 100.0
    elif overlap > 0:
        industry_match = round(overlap * 100, 2)
    else:
        industry_match = None

    geography_terms = _target_geography_terms(product.target_market)
    geography_match: float | None
    if geography_terms and any(term in all_text for term in geography_terms):
        geography_match = 100.0
    else:
        geography_match = None
    size_status = account.attributes.get("company_size_status")
    size_in_range = account.attributes.get("company_size_in_range")
    size_match: float | None = (
        100.0
        if size_status == "VERIFIED" and size_in_range is True
        else 0.0
        if size_status == "VERIFIED" and size_in_range is False
        else None
    )
    if account.attributes.get("qualification_status") == "DISQUALIFIED":
        industry_match = 0.0
        geography_match = 0.0
        size_match = 0.0
        signal_strength = 0.0
    score_signal = (
        signal_match
        if account.attributes.get("qualification_status") != "DISQUALIFIED"
        else None
    )
    scores = score_account(
        industry_match=industry_match,
        size_match=size_match,
        geography_match=geography_match,
        signal_strength=signal_strength,
        signal_recency=(
            signal_decay(top_signal_event_date) * 100
            if score_signal and top_signal_event_date is not None
            else None
            if score_signal
            else 0
        ),
        evidence_coverage=min(100, len(facts) * 30),
        source_quality=(
            sum(item.trust_score for item in source_rows)
            / max(1, len(source_rows))
            * 100
        ),
        fit_evidence=fit_evidence,
        signal_evidence=signal_evidence,
        retrieval_coverage=(
            retrieval_summary.coverage if retrieval_summary.attempted else None
        ),
    )
    snapshot = AccountScoreSnapshotRow(
        workspace_id=run.workspace_id,
        account_id=account.id,
        research_run_id=run.id,
        scoring_version="intelligence-quality-v3",
        scores=scores.model_dump(mode="json"),
        weights={"fit": 0.55, "intent": 0.45, "confidence_gate": True},
        inputs={
            "target_keyword_overlap": overlap,
            "verified_signal": signal_match is not None,
            "verified_signal_count": len(signal_matches),
            "source_quality": source.trust_score,
            "unknown_size_excluded_from_fit_denominator": size_match is None,
            "qualification_status": account.attributes.get(
                "qualification_status", "INSUFFICIENT_EVIDENCE"
            ),
        },
    )
    session.add(snapshot)
    await session.flush()
    for factor_type, breakdown in (
        ("fit", scores.fit),
        ("intent", scores.intent),
        ("confidence", scores.confidence),
    ):
        for component in breakdown.components:
            session.add(
                AccountScoreFactorRow(
                    workspace_id=run.workspace_id,
                    score_snapshot_id=snapshot.id,
                    factor_type=factor_type,
                    label=component.label,
                    value=component.value,
                    weight=component.weight,
                    contribution=component.contribution,
                    reason="Deterministic input derived from persisted evidence",
                    evidence_ids=component.evidence_ids,
                )
            )
    signal_models: list[Signal] = []
    why_now: list[EvidenceClaim] = []
    for signal_type, fact, event_date in signal_matches:
        # Undated events keep their full base strength rather than borrowing the
        # freshness of the moment we happened to fetch the page.
        adjusted = signal_strength / 100 * (
            signal_decay(event_date) if event_date is not None else 1.0
        )
        high_relevance_types = {
            "SUPPORT_HIRING",
            "CUSTOMER_SUCCESS_HIRING",
            "NEW_MARKET",
            "ENTERPRISE_EXPANSION",
            "CUSTOMER_GROWTH_INDICATOR",
            "TECHNOLOGY_CHANGE",
        }
        relevance = 0.95 if signal_type in high_relevance_types else 0.65
        signal_source = source_by_id.get(fact.source_id)
        source_role = (
            str(signal_source.provenance.get("source_role") or SourceRole.OTHER.value)
            if signal_source
            else SourceRole.OTHER.value
        )
        entity_match_score = (
            attachment_by_fact_id[fact.id].entity_match_confidence
            if fact.id in attachment_by_fact_id
            else 0.0
        )
        attachment = attachment_by_fact_id.get(fact.id)
        signal_row = IntentSignalRow(
            workspace_id=run.workspace_id,
            account_id=account.id,
            signal_type=signal_type,
            title=f"Verified {signal_type} signal",
            description=fact.claim,
            observed_at=fact.observed_at,
            expires_at=None,
            base_strength=signal_strength / 100,
            relevance=relevance,
            confidence=float(fact.confidence),
            adjusted_strength=adjusted,
            evidence_ids=[str(fact.id)],
        )
        session.add(signal_row)
        await session.flush()
        signal_models.append(
            Signal(
                id=str(signal_row.id),
                signal_type=signal_type,
                description=fact.claim,
                observed_at=fact.observed_at,
                strength=adjusted,
                evidence_ids=[str(fact.id)],
                entity_match_score=entity_match_score,
                event_confidence=float(fact.confidence),
                relevance=relevance,
                source_role=source_role,
                subject_entity=(
                    attachment.subject_entity if attachment else fact.subject
                ),
                canonical_subject_domain=(
                    attachment.canonical_subject_domain
                    if attachment
                    else account.domain
                ),
                event_date=event_date,
                source_id=str(fact.source_id),
                supporting_passage=fact.passage,
                claim_scope=(
                    attachment.claim_scope.value
                    if attachment
                    else ClaimScope.COMPANY_LEVEL.value
                ),
                claim_scope_compatible=bool(
                    attachment and attachment.claim_scope_compatible
                ),
                attachment_decision=AttachmentDecision.ATTACHED.value,
                rejection_reason=None,
            )
        )
        why_now.append(
            EvidenceClaim(
                statement=fact.claim,
                status=ClaimStatus.SUPPORTED,
                confidence=float(fact.confidence),
                evidence_ids=[str(fact.id)],
            )
        )
    qualification = str(
        account.attributes.get("qualification_status") or "INSUFFICIENT_EVIDENCE"
    )
    competitor = account.attributes.get("competitor")
    direct_competitor_conflict = bool(
        isinstance(competitor, dict)
        and competitor.get("classification") == "DIRECT_COMPETITOR"
        and competitor.get("automatic_rejection_eligible")
    )
    brief_state = decide_brief_state(
        identity_verified=(
            account.domain in identity_record.verified_official_domains
            and identity_record.identity_confidence >= 0.8
        ),
        unresolved_identity_warnings=(
            identity_record.unresolved_identity_warnings
        ),
        qualification_status=qualification,
        has_supported_icp_fact=bool(facts),
        has_actionable_signal=bool(signal_matches),
        supported_important_claims=not rejected_evidence,
        direct_competitor_conflict=direct_competitor_conflict,
    )
    band, recommended_action = priority_band(
        scores,
        qualification_status=qualification,
        has_verified_signal=signal_match is not None,
    )
    if brief_state == BriefState.IDENTITY_REVIEW_REQUIRED:
        recommended_action = "Resolve entity ownership before using this account."
    elif brief_state == BriefState.DO_NOT_TARGET:
        recommended_action = "Do not target this account."
    elif brief_state == BriefState.MONITOR:
        recommended_action = "Monitor for a verified, account-specific trigger."
    if signal_match:
        signal_type, fact, _ = signal_match
        account.attributes = {
            **account.attributes,
            "top_signal": fact.claim,
            "top_signal_type": signal_type,
            "recommended_action": recommended_action,
            "priority_band": band,
            "research_candidate": qualification != "QUALIFIED",
            "brief_state": brief_state.value,
            "company_identity": identity_record.as_persisted_dict(),
            "evidence_attachment_audit": [
                {
                    "evidence_id": str(fact_id),
                    **assessment.as_persisted_dict(),
                }
                for fact_id, assessment in attachment_by_fact_id.items()
            ],
        }
    else:
        account.attributes = {
            **account.attributes,
            "top_signal": "No verified current signal",
            "top_signal_type": None,
            "recommended_action": recommended_action,
            "priority_band": band,
            "research_candidate": True,
            "brief_state": brief_state.value,
            "company_identity": identity_record.as_persisted_dict(),
            "evidence_attachment_audit": [
                {
                    "evidence_id": str(fact_id),
                    **assessment.as_persisted_dict(),
                }
                for fact_id, assessment in attachment_by_fact_id.items()
            ],
        }
    account.evidence_ids = [str(item.id) for item in facts]
    account.attributes = {
        **account.attributes,
        "source_ids": [str(item.id) for item in source_rows],
    }
    run.budgets = {
        **run.budgets,
        "searches_used": run.searches_used,
        "documents_used": run.documents_used,
        "search_limit": settings.max_research_searches,
        "document_limit": settings.max_research_documents,
        "estimated_provider_cost_usd": run.budgets.get(
            "estimated_provider_cost_usd", 0
        ),
        "cost_status": "ESTIMATE_ONLY",
    }
    session.add(
        AccountResearchSnapshotRow(
            workspace_id=run.workspace_id,
            account_id=account.id,
            research_run_id=run.id,
            summary={
                "source_claim": facts[0].claim,
                "company_identity": identity_record.as_persisted_dict(),
                "attachment_audit": [
                    {
                        "evidence_id": str(fact_id),
                        **assessment.as_persisted_dict(),
                    }
                    for fact_id, assessment in attachment_by_fact_id.items()
                ],
                "rejected_or_ambiguous_evidence": rejected_evidence,
            },
            source_ids=list(dict.fromkeys(str(item.source_id) for item in facts)),
            evidence_ids=[str(item.id) for item in facts],
            status="completed",
        )
    )
    account_domain = await repository.account_domain(session, account)
    if account_domain is None:
        raise ValueError("Account score snapshot was not persisted")
    evidence_domains = [repository.evidence_domain(item) for item in facts]
    source_domains = [repository.source_domain(item) for item in source_rows]
    draft_id = uuid.uuid4()
    unknowns = [
        reason
        for reason in _attribute_string_list(
            account.attributes.get("qualification_reasons", [])
        )
        if "unknown" in str(reason).lower()
        or "unverified" in str(reason).lower()
        or "remain" in str(reason).lower()
    ]
    # Substring matching alone misclassified neutral notes: "Competitor overlap
    # requires research; no automatic rejection" contains "competitor" and was
    # surfaced to the founder as "Mismatch:", reading as a competitor conflict the
    # system had explicitly declined to assert.
    icp_mismatches = [
        reason
        for reason in _attribute_string_list(
            account.attributes.get("qualification_reasons", [])
        )
        if any(
            marker in str(reason).lower()
            for marker in ("outside", "mismatch", "competitor", "disqualif")
        )
        and not any(
            marker in str(reason).lower() for marker in NON_MISMATCH_MARKERS
        )
    ]
    hypotheses = [
        EvidenceClaim(
            statement=(
                f"{account.name} may benefit from {product.product}; "
                "this requires discovery validation."
            ),
            status=ClaimStatus.HYPOTHESIS,
            confidence=0.35,
            evidence_ids=[],
        )
    ]
    reason_not_to_target = (
        "Entity ownership is unresolved."
        if brief_state == BriefState.IDENTITY_REVIEW_REQUIRED
        else "The account is disqualified or has a direct-competitor conflict."
        if brief_state == BriefState.DO_NOT_TARGET
        else "No timely, account-specific buying signal is verified."
        if brief_state == BriefState.MONITOR
        else None
    )
    next_research_step = (
        "Verify legal ownership and official-domain relationships."
        if brief_state == BriefState.IDENTITY_REVIEW_REQUIRED
        else "Verify the missing ICP criteria with bounded first-party research."
        if brief_state == BriefState.RESEARCH_CANDIDATE
        else "Watch first-party news, careers, and product announcements."
        if brief_state == BriefState.MONITOR
        else None
    )
    campaign_subject = (
        f"Question for {account.name}"
        if brief_state == BriefState.FOUNDER_READY
        else f"Research checkpoint for {account.name}"
    )
    campaign_body = (
        (
            f"Hi {account.name} team,\n\n"
            f"We reviewed a public source linked in this brief. "
            f"We help teams explore {product.product}. "
            "Would a short, human-reviewed discovery conversation be useful?\n\n"
            "This draft has not been sent."
        )
        if brief_state == BriefState.FOUNDER_READY
        else (
            "No outreach is recommended. Resolve the identity, qualification, "
            "or timely-signal gaps documented in this brief first."
        )
    )
    brief_payload = AccountOpportunityBrief(
        account=account_domain,
        why_it_fits=[
            EvidenceClaim(
                statement=facts[0].claim,
                status=ClaimStatus.SUPPORTED,
                confidence=float(facts[0].confidence),
                evidence_ids=[str(facts[0].id)],
            )
        ],
        why_now=why_now,
        pain_hypotheses=hypotheses,
        recommended_problem="Validate whether the confirmed target problem is present.",
        recommended_offer=(
            f"A human-reviewed exploration of {product.product}."
            if brief_state == BriefState.FOUNDER_READY
            else "No outreach offer until the documented evidence gaps are resolved."
        ),
        recommended_action=str(account.attributes["recommended_action"]),
        risks=[
            (
                "Company size, location, and industry remain unverified unless "
                "explicitly sourced."
            ),
            "Pain is a hypothesis until confirmed in discovery.",
            "Recommended actions are research and human-review actions, never sends.",
        ],
        evidence=evidence_domains,
        sources=source_domains,
        signals=signal_models,
        verified_facts=[
            EvidenceClaim(
                statement=item.claim,
                status=ClaimStatus.SUPPORTED,
                confidence=float(item.confidence),
                evidence_ids=[str(item.id)],
            )
            for item in facts[:5]
        ],
        unknowns=unknowns,
        research_candidate=bool(
            account.attributes.get("research_candidate", True)
        ),
        brief_state=brief_state.value,
        verified_identity=identity_record.as_persisted_dict(),
        verified_icp_facts=[
            EvidenceClaim(
                statement=facts[0].claim,
                status=ClaimStatus.SUPPORTED,
                confidence=float(facts[0].confidence),
                evidence_ids=[str(facts[0].id)],
            )
        ],
        icp_mismatches=icp_mismatches,
        unknown_icp_facts=unknowns,
        current_signals=signal_models,
        rejected_or_ambiguous_evidence=rejected_evidence,
        hypotheses=hypotheses,
        reason_not_to_target=reason_not_to_target,
        next_research_step=next_research_step,
        retrieval=retrieval_summary,
        campaign=CampaignDraft(
            id=str(draft_id),
            account_id=str(account.id),
            subject=campaign_subject,
            body=campaign_body,
            evidence_ids=[str(item.id) for item in facts],
        ),
    )
    prior_version = await session.scalar(
        select(OpportunityBriefRow.version)
        .where(OpportunityBriefRow.account_id == account.id)
        .order_by(desc(OpportunityBriefRow.version))
        .limit(1)
    )
    brief_row = OpportunityBriefRow(
        workspace_id=run.workspace_id,
        account_id=account.id,
        research_run_id=run.id,
        payload=brief_payload.model_dump(mode="json"),
        evidence_ids=[str(item.id) for item in facts],
        version=(prior_version or 0) + 1,
        generated_at=_now(),
    )
    session.add(brief_row)
    await session.flush()
    campaign = CampaignDraftRow(
        id=draft_id,
        workspace_id=run.workspace_id,
        account_id=account.id,
        opportunity_brief_id=brief_row.id,
        subject=brief_payload.campaign.subject,
        body=brief_payload.campaign.body,
        status="draft",
        evidence_ids=brief_payload.campaign.evidence_ids,
        risk_flags=brief_payload.risks,
    )
    session.add(campaign)
    await session.flush()
    session.add(
        ApprovalRequestRow(
            workspace_id=run.workspace_id,
            campaign_draft_id=draft_id,
            status="pending",
            requested_by="system",
            decided_by=None,
            decided_at=None,
        )
    )


async def execute_job(
    kind: str,
    target_id: str,
    *,
    workspace_id: str | None = None,
    actor_id: str | None = None,
) -> None:
    """Dispatch a queued job.

    `workspace_id` is a defence-in-depth check: the enqueuing route already verified
    membership, and this confirms the target still belongs to the workspace that
    asked for it before any work is done.
    """

    if workspace_id is not None:
        await _assert_job_target_workspace(kind, target_id, workspace_id)
    del actor_id  # Reserved for attribution; audit rows are written by each stage.
    if kind == "research":
        await execute_research(target_id)
    elif kind == "discover_accounts":
        await discover_accounts(target_id)
    elif kind == "research_account":
        await research_account(target_id)
    elif kind == "regenerate_brief":
        await regenerate_brief(target_id)
    else:
        raise ValueError("Unsupported job kind")


_JOB_TARGET_MODELS: dict[str, type[ResearchRunRow] | type[ICPProfileRow] | type[AccountRow]] = {
    "research": ResearchRunRow,
    "discover_accounts": ICPProfileRow,
    "research_account": AccountRow,
    "regenerate_brief": AccountRow,
}


async def _assert_job_target_workspace(
    kind: str, target_id: str, workspace_id: str
) -> None:
    model = _JOB_TARGET_MODELS.get(kind)
    if model is None:
        raise ValueError("Unsupported job kind")
    async with SessionFactory() as session:
        row = await session.get(model, uuid.UUID(target_id))
        if row is None:
            raise KeyError(f"{kind} target not found")
        if str(row.workspace_id) != workspace_id:
            raise PermissionError("Job target belongs to another workspace")


async def record_job_failure(kind: str, target_id: str, reason: str) -> None:
    """Persist a terminal job failure so the product can show it.

    Without this a exhausted job is visible only in worker logs, and the UI cannot
    tell "still running" apart from "gave up".
    """

    error = {
        "category": "JOB_FAILED",
        "message": "Background research did not complete after repeated attempts",
        "reason": reason,
        "retryable": False,
    }
    async with SessionFactory() as session:
        if kind in {"research", "discover_accounts"}:
            run = await session.get(ResearchRunRow, uuid.UUID(target_id))
            if kind == "discover_accounts":
                icp = await session.get(ICPProfileRow, uuid.UUID(target_id))
                run = (
                    await session.get(ResearchRunRow, icp.research_run_id)
                    if icp is not None
                    else None
                )
            if run is not None:
                run.status = "failed"
                run.current_stage = "job_failed"
                run.error = error
                run.updated_at = _now()
                await session.commit()
            return

        account = await session.get(AccountRow, uuid.UUID(target_id))
        if account is not None:
            account.attributes = {
                **account.attributes,
                "last_job_error": error,
                "recommended_action": (
                    "Background research failed; retry before changing status."
                ),
            }
            account.last_researched_at = _now()
            await session.commit()


async def research_account(
    account_id: str, provider: LiveResearchProvider | None = None
) -> None:
    provider = provider or LiveResearchProvider()
    async with SessionFactory() as session:
        account = await session.get(AccountRow, uuid.UUID(account_id))
        if account is None or account.icp_profile_id is None:
            return
        icp = await session.get(ICPProfileRow, account.icp_profile_id)
        if icp is None:
            return
        run = await session.get(ResearchRunRow, icp.research_run_id)
        if run is None:
            return
        product = await session.get(ProductProfileRow, run.product_id)
        if product is None:
            return
        direct_sources, direct_facts, retrieval = (
            await _fetch_supplied_official_sources(
                session,
                run,
                provider,
                company_name=account.name,
                domain=account.domain,
            )
        )
        # Persist on the account so the brief can report what we actually read,
        # rather than presenting a one-page-out-of-eight run as a complete one.
        account.attributes = {
            **account.attributes,
            "retrieval": retrieval.model_dump(mode="json"),
        }
        # Identity verification and evidence extraction are different questions.
        # Fetching the supplied domain and confirming the post-redirect canonical
        # domain still matches IS the verification; whether we could mine a usable
        # passage from the page is a separate, weaker concern. Conflating them
        # reported real companies as unverifiable simply because their homepage
        # copy was terse.
        if not direct_sources:
            raw_identity = account.attributes.get("company_identity")
            identity = (
                {str(key): value for key, value in raw_identity.items()}
                if isinstance(raw_identity, dict)
                else {}
            )
            identity["unresolved_identity_warnings"] = [
                "The supplied official domain could not be verified."
            ]
            identity["identity_confidence"] = 0.0
            account.attributes = {
                **account.attributes,
                "company_identity": identity,
                "domain_validation": "UNVERIFIED",
                "domain_confidence": 0.0,
                "brief_state": "IDENTITY_REVIEW_REQUIRED",
                "recommended_action": "Resolve company identity before research.",
            }
            account.last_researched_at = _now()
            brief_row = await session.scalar(
                select(OpportunityBriefRow)
                .where(OpportunityBriefRow.account_id == account.id)
                .order_by(desc(OpportunityBriefRow.version))
                .limit(1)
            )
            if brief_row is not None:
                brief_row.payload = {
                    **brief_row.payload,
                    "brief_state": "IDENTITY_REVIEW_REQUIRED",
                    "verified_identity": identity,
                    "verified_facts": [],
                    "verified_icp_facts": [],
                    "icp_mismatches": [],
                    "unknowns": [
                        "Official company identity",
                        "ICP fit",
                        "Current supported signal",
                    ],
                    "unknown_icp_facts": [
                        "Industry",
                        "Geography",
                        "Employee size",
                        "Business model",
                    ],
                    "current_signals": [],
                    "rejected_or_ambiguous_evidence": [],
                    "recommended_problem": (
                        "The supplied official domain could not be verified."
                    ),
                    "recommended_offer": "No outreach recommendation",
                    "recommended_action": (
                        "Resolve company identity before research."
                    ),
                    "reason_not_to_target": "Entity ownership is unresolved.",
                    "next_research_step": (
                        "Verify legal ownership and official-domain relationships."
                    ),
                }
            await session.commit()
            return
        source = direct_sources[0]
        sources = list(direct_sources)
        facts = list(direct_facts)
        if search_provider_configured():
            enriched_sources, enriched_facts = await _research_account_sources(
                session,
                run,
                provider,
                company_name=account.name,
                domain=account.domain,
                initial_source=source,
                initial_facts=facts,
            )
            source_by_id = {item.id: item for item in [*sources, *enriched_sources]}
            fact_by_id = {item.id: item for item in [*facts, *enriched_facts]}
            sources = list(source_by_id.values())
            facts = list(fact_by_id.values())
        official_sources = [
            item
            for item in sources
            if _normalized_company_domain(item.canonical_url) == account.domain
        ]
        combined_text = " ".join(item.cleaned_text for item in official_sources)
        employee_band, size_status, size_in_range = _company_size_from_text(
            combined_text
        )
        qualification, reasons = _qualify_account(
            combined_text,
            domain_validated=(
                _normalized_company_domain(source.canonical_url) == account.domain
            ),
            size_in_range=size_in_range,
        )
        lowered_text = combined_text.lower()
        account.industry = (
            "B2B SaaS"
            if any(
                term in lowered_text
                for term in ("b2b saas", "enterprise software", "software as a service")
            )
            else None
        )
        account.location = (
            "India"
            if any(
                term in lowered_text
                for term in (
                    "india",
                    "bengaluru",
                    "bangalore",
                    "hyderabad",
                    "pune",
                    "mumbai",
                    "gurugram",
                    "chennai",
                )
            )
            else None
        )
        account.employee_band = employee_band
        account.evidence_ids = list(dict.fromkeys(str(item.id) for item in facts))
        account.attributes = {
            **account.attributes,
            "qualification_status": qualification,
            "qualification_reasons": reasons,
            "company_size_status": size_status,
            "company_size_in_range": size_in_range is True,
            "domain_validation": "VALIDATED",
            "registrable_domain": account.domain,
            "domain_confidence": 0.99,
            "qualification_coverage": (
                1.0 if qualification == "QUALIFIED" else 0.75
            ),
            "source_ids": [str(item.id) for item in sources],
        }
        await _score_and_brief(session, run, product, icp, account, source, facts)
        account.last_researched_at = _now()
        await session.commit()


async def regenerate_brief(account_id: str) -> None:
    async with SessionFactory() as session:
        account = await session.get(AccountRow, uuid.UUID(account_id))
        if account is None or account.icp_profile_id is None:
            return
        icp = await session.get(ICPProfileRow, account.icp_profile_id)
        if icp is None:
            return
        run = await session.get(ResearchRunRow, icp.research_run_id)
        if run is None:
            return
        product = await session.get(ProductProfileRow, run.product_id)
        if product is None:
            return
        fact_ids: list[uuid.UUID] = []
        for value in account.evidence_ids:
            try:
                fact_ids.append(uuid.UUID(value))
            except ValueError:
                continue
        facts = list(
            (
                await session.scalars(
                    select(EvidenceFactRow).where(EvidenceFactRow.id.in_(fact_ids))
                )
            ).all()
        )
        if not facts:
            return
        source = await session.get(SourceDocumentRow, facts[0].source_id)
        if source is None:
            return
        await _score_and_brief(session, run, product, icp, account, source, facts)
        await session.commit()
