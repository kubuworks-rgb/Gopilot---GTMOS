from __future__ import annotations

import hashlib
import re
import uuid
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
    Signal,
)
from apps.api.app.providers.live import GatewayProviderError, LiveResearchProvider
from apps.api.app.repositories.postgres import repository
from apps.api.app.services.scoring import score_account, signal_decay
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
SOURCE_CHUNK_SIZE = 1800
SOURCE_CHUNK_STEP = 1100


def _now() -> datetime:
    return datetime.now(UTC)


def _tokens(value: str) -> set[str]:
    return {
        match.group(0).lower()
        for match in WORD_PATTERN.finditer(value)
        if match.group(0).lower()
        not in {"and", "the", "for", "with", "from", "that", "this", "into"}
    }


def _sentences(text: str) -> list[str]:
    return [
        value.strip()
        for value in SENTENCE_PATTERN.split(text)
        if 45 <= len(value.strip()) <= 700
    ]


def _evidence_passages(text: str, context: str) -> list[str]:
    context_tokens = _tokens(context)
    minimum_overlap = 1 if len(context_tokens) <= 3 else 2
    ranked: list[tuple[int, float, int, str]] = []
    for index, sentence in enumerate(_sentences(text)):
        lowered = sentence.lower()
        if any(term in lowered for term in BOILERPLATE_TERMS):
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
        trust_score=0.72,
        permission_classification="public",
        status="retrieved",
        provenance={
            "retrieved_by": "research-gateway",
            "backend": source.backend,
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
        else _sentences(source.text)[:2]
    )
    if not evidence_context and not candidates and source.text.strip():
        candidates = [source.text.strip()[:700]]
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
            session.add(
                GTMFindingRow(
                    workspace_id=run.workspace_id,
                    research_run_id=run.id,
                    category=categories[index % len(categories)],
                    claim=fact.claim,
                    confidence=float(fact.confidence),
                    status=fact.status,
                    evidence_ids=[str(fact.id)],
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
    return host


def _is_candidate_company_page(result: SearchResult) -> bool:
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


def _qualify_account(
    text: str,
    *,
    domain_validated: bool,
    size_in_range: bool | None,
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
    direct_competitor = any(
        term in lowered
        for term in (
            "ai customer support platform",
            "customer support automation platform",
            "automate customer support with ai",
        )
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
    if direct_competitor:
        reasons.append("The company appears to sell direct support automation.")
        return "DISQUALIFIED", reasons
    if not domain_validated:
        return "INSUFFICIENT_EVIDENCE", reasons
    if is_saas and is_india and has_support_operations and size_in_range is True:
        return "QUALIFIED", reasons
    if is_saas and is_india:
        return "BORDERLINE", reasons
    return "INSUFFICIENT_EVIDENCE", reasons


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
            "ACCOUNT_SIGNAL_RESEARCH",
            (f'"{company_name}" (funding OR launch OR expansion OR partnership)'),
            "news",
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


async def discover_accounts(
    icp_id: str, provider: LiveResearchProvider | None = None
) -> None:
    provider = provider or LiveResearchProvider()
    async with SessionFactory() as session:
        icp = await session.get(ICPProfileRow, uuid.UUID(icp_id))
        if icp is None or icp.selected_at is None:
            return
        run = await session.get(ResearchRunRow, icp.research_run_id)
        if run is None:
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
        candidates: dict[str, SearchResult] = {}
        discovery_diagnostics = {
            "search_results": 0,
            "candidate_pages": 0,
            "fetch_failures": 0,
            "no_evidence": 0,
            "preliminary_rejections": 0,
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
                    limit=min(5, settings.max_account_candidates),
                    purpose="account_discovery",
                )
                run.searches_used += 1
                discovery_diagnostics["search_results"] += len(response.results)
                for item in response.results:
                    domain = _normalized_company_domain(str(item.url))
                    if not domain or not _is_candidate_company_page(item):
                        continue
                    candidates.setdefault(domain, item)
                discovery_diagnostics["candidate_pages"] = len(candidates)
            except GatewayProviderError:
                continue
        created = 0
        for domain, result in candidates.items():
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
            preliminary_text = f"{result.snippet} {source.cleaned_text}"
            _, _, preliminary_size_in_range = _company_size_from_text(preliminary_text)
            preliminary_qualification, _ = _qualify_account(
                preliminary_text,
                domain_validated=domain_validated,
                size_in_range=preliminary_size_in_range,
            )
            if preliminary_qualification == "INSUFFICIENT_EVIDENCE":
                discovery_diagnostics["preliminary_rejections"] += 1
                continue
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
                [result.snippet, *(item.cleaned_text for item in official_sources)]
            )
            employee_band, size_status, size_in_range = _company_size_from_text(
                combined_text
            )
            qualification, qualification_reasons = _qualify_account(
                combined_text,
                domain_validated=domain_validated,
                size_in_range=size_in_range,
            )
            if qualification == "INSUFFICIENT_EVIDENCE":
                discovery_diagnostics["final_rejections"] += 1
                continue
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
                        "qualification_status": qualification,
                        "qualification_reasons": qualification_reasons,
                        "company_size_status": size_status,
                        "company_size_in_range": size_in_range is True,
                        "discovery_source": str(result.url),
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
                    "qualification_status": qualification,
                    "qualification_reasons": qualification_reasons,
                    "company_size_status": size_status,
                    "company_size_in_range": size_in_range is True,
                    "discovery_source": str(result.url),
                    "domain_validation": (
                        "VALIDATED" if domain_validated else "MISMATCH"
                    ),
                    "source_ids": [str(item.id) for item in sources],
                }
            await _score_and_brief(session, run, product, icp, account, source, facts)
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
    haystack = re.sub(
        r"[^a-z0-9]",
        "",
        f"{result.title} {result.snippet}".lower(),
    )
    brand = re.sub(r"[^a-z0-9]", "", _domain_brand(domain).lower())
    if len(brand) >= 4 and brand in haystack:
        return True
    company = re.sub(r"[^a-z0-9]", "", company_name.lower())
    return len(company) >= 4 and company in haystack


def _signals_from_facts(
    facts: list[EvidenceFactRow],
    source_by_id: dict[uuid.UUID, SourceDocumentRow] | None = None,
) -> list[tuple[str, EvidenceFactRow]]:
    matches: list[tuple[str, EvidenceFactRow]] = []
    seen: set[tuple[str, uuid.UUID]] = set()
    for fact in facts:
        lowered = fact.claim.lower()
        for signal_type, term_groups in SIGNAL_RULES.items():
            if not all(any(term in lowered for term in group) for group in term_groups):
                continue
            source = source_by_id.get(fact.source_id) if source_by_id else None
            if source is not None and signal_type != "CUSTOMER_GROWTH_INDICATOR":
                dated_or_event_page = source.published_at is not None or any(
                    marker in source.url.lower()
                    for marker in (
                        "/careers",
                        "/jobs",
                        "/news",
                        "/blog",
                        "/press",
                        "/announcements",
                    )
                )
                if not dated_or_event_page:
                    continue
            key = (signal_type, fact.id)
            if key not in seen:
                matches.append((signal_type, fact))
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
    target_tokens = _tokens(product.target_market)
    evidence_tokens = _tokens(" ".join(item.claim for item in facts))
    overlap = len(target_tokens & evidence_tokens) / max(1, len(target_tokens))
    source_ids = list(dict.fromkeys(item.source_id for item in facts))
    source_rows = list(
        (
            await session.scalars(
                select(SourceDocumentRow)
                .where(SourceDocumentRow.id.in_(source_ids))
                .order_by(SourceDocumentRow.created_at)
            )
        ).all()
    )
    signal_matches = _signals_from_facts(facts, {item.id: item for item in source_rows})
    signal_match = signal_matches[0] if signal_matches else None
    signal_evidence = [str(item[1].id) for item in signal_matches]
    fit_evidence = [str(facts[0].id)]
    observed_at = signal_match[1].observed_at if signal_match else _now()
    signal_strength = (
        min(100.0, 62.0 + len(signal_matches) * 8) if signal_match else 0.0
    )
    all_text = " ".join(item.claim for item in facts).lower()
    industry_match = (
        100.0
        if any(term in all_text for term in ("b2b saas", "enterprise software"))
        else round(overlap * 100, 2)
    )
    geography_match = (
        100.0
        if any(
            term in all_text
            for term in ("india", "bengaluru", "bangalore", "hyderabad", "pune")
        )
        else 0.0
    )
    size_match = (
        100.0
        if account.attributes.get("company_size_status") == "VERIFIED"
        and account.attributes.get("company_size_in_range") is True
        else 0.0
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
        signal_recency=signal_decay(observed_at) * 100 if score_signal else 0,
        evidence_coverage=min(100, len(facts) * 30),
        source_quality=source.trust_score * 100,
        fit_evidence=fit_evidence,
        signal_evidence=signal_evidence,
    )
    snapshot = AccountScoreSnapshotRow(
        workspace_id=run.workspace_id,
        account_id=account.id,
        research_run_id=run.id,
        scoring_version="real-gtm-v2",
        scores=scores.model_dump(mode="json"),
        weights={"fit": 0.55, "intent": 0.45, "confidence_gate": True},
        inputs={
            "target_keyword_overlap": overlap,
            "verified_signal": signal_match is not None,
            "verified_signal_count": len(signal_matches),
            "source_quality": source.trust_score,
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
    for signal_type, fact in signal_matches:
        adjusted = signal_strength / 100 * signal_decay(fact.observed_at)
        signal_row = IntentSignalRow(
            workspace_id=run.workspace_id,
            account_id=account.id,
            signal_type=signal_type,
            title=f"Verified {signal_type} signal",
            description=fact.claim,
            observed_at=fact.observed_at,
            expires_at=None,
            base_strength=signal_strength / 100,
            relevance=0.8,
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
    if signal_match:
        signal_type, fact = signal_match
        qualification = str(
            account.attributes.get("qualification_status") or "INSUFFICIENT_EVIDENCE"
        )
        recommended_action = (
            "Prioritize for human review of the verified trigger"
            if qualification == "QUALIFIED"
            else "Review qualification gaps before considering any outreach"
        )
        account.attributes = {
            **account.attributes,
            "top_signal": fact.claim,
            "top_signal_type": signal_type,
            "recommended_action": recommended_action,
        }
    else:
        size_unknown = (
            account.attributes.get("company_size_status", "UNKNOWN") == "UNKNOWN"
        )
        account.attributes = {
            **account.attributes,
            "top_signal": "No verified current signal",
            "top_signal_type": None,
            "recommended_action": (
                "Research missing company-size evidence"
                if size_unknown
                else "Monitor for a verified buying trigger"
            ),
        }
    session.add(
        AccountResearchSnapshotRow(
            workspace_id=run.workspace_id,
            account_id=account.id,
            research_run_id=run.id,
            summary={"source_claim": facts[0].claim},
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
        pain_hypotheses=[
            EvidenceClaim(
                statement=(
                    f"{account.name} may benefit from {product.product}; "
                    "this requires discovery validation."
                ),
                status=ClaimStatus.HYPOTHESIS,
                confidence=0.35,
                evidence_ids=[],
            )
        ],
        recommended_problem="Validate whether the confirmed target problem is present.",
        recommended_offer=f"A human-reviewed exploration of {product.product}.",
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
        campaign=CampaignDraft(
            id=str(draft_id),
            account_id=str(account.id),
            subject=f"Question for {account.name}",
            body=(
                f"Hi {account.name} team,\n\n"
                f"We reviewed a public source linked in this brief. "
                f"We help teams explore {product.product}. "
                "Would a short, human-reviewed discovery conversation be useful?\n\n"
                "This draft has not been sent."
            ),
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


async def execute_job(kind: str, target_id: str) -> None:
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
        try:
            response = await provider.search(
                workspace_id=str(run.workspace_id),
                research_run_id=str(run.id),
                query=(
                    f"site:{account.domain} {account.name} about product careers "
                    "customer success support"
                ),
                limit=5,
                purpose="account_research",
            )
            same_domain = next(
                (
                    result
                    for result in response.results
                    if (urlsplit(str(result.url)).hostname or "")
                    .removeprefix("www.")
                    .lower()
                    == account.domain.lower()
                ),
                response.results[0] if response.results else None,
            )
            if same_domain is None:
                return
            source_input = await provider.fetch(
                workspace_id=str(run.workspace_id),
                research_run_id=str(run.id),
                url=str(same_domain.url),
            )
        except GatewayProviderError:
            return
        source, facts = await _persist_source(session, run, source_input)
        if not facts:
            return
        sources, facts = await _research_account_sources(
            session,
            run,
            provider,
            company_name=account.name,
            domain=account.domain,
            initial_source=source,
            initial_facts=facts,
        )
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
