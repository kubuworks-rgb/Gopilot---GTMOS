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
SIGNAL_TERMS = {
    "hiring": ("hiring", "job opening", "join our team", "vacancy"),
    "launch": ("launched", "launches", "new product", "now available"),
    "expansion": ("expansion", "expanding", "new market", "new office"),
    "funding": ("funding", "raised", "series a", "seed round"),
    "partnership": ("partnership", "partnered", "collaboration"),
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
        f"{product.product} {product.target_market} market",
        f"{product.target_market} companies",
        f"{product.target_market} hiring launch expansion",
        f"{product.product} competitors alternatives",
    ][: settings.max_research_searches]


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


def _validate_evidence(
    source: SourceDocumentRow, facts: list[EvidenceFactRow]
) -> None:
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
        queries = queries_override or build_research_queries(product)
        workflow_started = monotonic()
        run.status = "researching"
        run.current_stage = "market_intelligence"
        await session.commit()

        all_facts: list[EvidenceFactRow] = []
        failures: list[dict[str, object]] = []
        seen_urls: set[str] = set()
        for query in queries:
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
                task_type="web_search",
                query=query,
                status="running",
                source_strategy={"adapter": "search", "limit": 5},
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
                )
                await _tool_call(
                    session,
                    run,
                    agent_run.id,
                    "search",
                    {"query": query},
                    started,
                    status="completed",
                    backend=response.backend,
                )
                usable = 0
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
                task.status = "completed" if usable else "partial"
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
    target = product.target_market.strip()
    variants = (
        (
            "Core target",
            f"Organizations matching the confirmed target: {target}",
            ["Direct match to confirmed target market"],
        ),
        (
            "Trigger-led target",
            f"Organizations in {target} showing a verifiable change event",
            ["Current hiring, launch, expansion, funding, or partnership evidence"],
        ),
        (
            "Evidence-rich target",
            f"Organizations in {target} with enough public evidence for review",
            ["Multiple inspectable public-source claims"],
        ),
    )
    for index, (label, description, triggers) in enumerate(variants):
        selected_evidence = [evidence[index % len(evidence)]]
        session.add(
            ICPProfileRow(
                workspace_id=run.workspace_id,
                research_run_id=run.id,
                name=f"{target[:72]} — {label}",
                description=description,
                definition={
                    "firmographics": [target, "Publicly researchable organization"],
                    "pains": [
                        "GTM pain is unverified until discovery",
                        f"Potential relevance to {product.product}",
                    ],
                    "triggers": triggers,
                    "rationale": (
                        "Uses the user-confirmed target definition and separates "
                        "source-backed market context from hypotheses."
                    ),
                },
                confidence=0.78,
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
            f"{icp.description} company official website",
            f"{product.target_market} companies launch hiring",
            f"{product.target_market} organizations expansion",
        ]
        workflow_started = monotonic()
        candidates: dict[str, SearchResult] = {}
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
                    limit=min(10, settings.max_account_candidates),
                )
                run.searches_used += 1
                for item in response.results:
                    host = (urlsplit(str(item.url)).hostname or "").lower()
                    if not host or host in EXCLUDED_ACCOUNT_HOSTS:
                        continue
                    candidates.setdefault(host.removeprefix("www."), item)
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
                continue
            source, facts = await _persist_source(
                session,
                run,
                source_input,
                f"{product.target_market} {result.title} {domain}",
            )
            if not facts:
                continue
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
                    industry=None,
                    location=None,
                    employee_band=None,
                    business_model=None,
                    attributes={},
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
            }
        await session.commit()


def _account_name(title: str, domain: str) -> str:
    for separator in (" | ", " — ", " - ", " – "):
        if separator in title:
            title = title.split(separator, 1)[0]
            break
    clean = " ".join(title.split()).strip()
    return (clean or domain.split(".")[0].replace("-", " ").title())[:180]


def _signal_from_facts(
    facts: list[EvidenceFactRow],
) -> tuple[str, EvidenceFactRow] | None:
    for fact in facts:
        lowered = fact.claim.lower()
        for signal_type, terms in SIGNAL_TERMS.items():
            if any(term in lowered for term in terms):
                return signal_type, fact
    return None


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
    signal_match = _signal_from_facts(facts)
    signal_evidence = [str(signal_match[1].id)] if signal_match else []
    fit_evidence = [str(facts[0].id)]
    observed_at = signal_match[1].observed_at if signal_match else _now()
    signal_strength = 72.0 if signal_match else 0.0
    scores = score_account(
        industry_match=round(overlap * 100, 2),
        size_match=0,
        geography_match=round(overlap * 100, 2),
        signal_strength=signal_strength,
        signal_recency=signal_decay(observed_at) * 100 if signal_match else 0,
        evidence_coverage=min(100, len(facts) * 30),
        source_quality=source.trust_score * 100,
        fit_evidence=fit_evidence,
        signal_evidence=signal_evidence,
    )
    snapshot = AccountScoreSnapshotRow(
        workspace_id=run.workspace_id,
        account_id=account.id,
        research_run_id=run.id,
        scoring_version="live-v1",
        scores=scores.model_dump(mode="json"),
        weights={"fit": 0.55, "intent": 0.45, "confidence_gate": True},
        inputs={
            "target_keyword_overlap": overlap,
            "verified_signal": signal_match is not None,
            "source_quality": source.trust_score,
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
    if signal_match:
        signal_type, fact = signal_match
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
        account.attributes = {
            **account.attributes,
            "top_signal": fact.claim,
            "recommended_action": "Review the verified signal and source before outreach",
        }
    else:
        account.attributes = {
            **account.attributes,
            "top_signal": "No verified current signal",
            "recommended_action": "Research current trigger evidence before outreach",
        }
    session.add(
        AccountResearchSnapshotRow(
            workspace_id=run.workspace_id,
            account_id=account.id,
            research_run_id=run.id,
            summary={"source_claim": facts[0].claim},
            source_ids=[str(source.id)],
            evidence_ids=[str(item.id) for item in facts],
            status="completed",
        )
    )
    account_domain = await repository.account_domain(session, account)
    if account_domain is None:
        raise ValueError("Account score snapshot was not persisted")
    evidence_domains = [repository.evidence_domain(item) for item in facts]
    source_domain = repository.source_domain(source)
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
            "Company size, location, and industry remain unverified unless explicitly sourced.",
            "Pain is a hypothesis until confirmed in discovery.",
        ],
        evidence=evidence_domains,
        sources=[source_domain],
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
                query=f"{account.name} {account.domain} hiring launch expansion",
                limit=5,
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
        await _score_and_brief(
            session, run, product, icp, account, source, facts
        )
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
        await _score_and_brief(
            session, run, product, icp, account, source, facts
        )
        await session.commit()
