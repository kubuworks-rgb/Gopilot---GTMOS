from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select

from apps.api.app.db.models import AccountRow, QAEvaluationRow, ResearchRunRow
from apps.api.app.db.session import SessionFactory
from apps.api.app.domain.models import QAEvaluationInput
from apps.api.app.repositories.postgres import repository


RUN_ID = uuid.UUID("a85e9a35-09f3-4dd8-b77e-7d3941adacd7")
EVALUATOR = "codex-manual-qa-2026-07-23"

# These judgments were manually curated after opening the primary evidence URLs.
# They intentionally record the pre-fix diagnostic run so its failures remain auditable.
EVALUATIONS: dict[str, dict[str, object]] = {
    "go.hrone.cloud": {
        "company_validity": "REAL",
        "domain_correctness": "INCORRECT",
        "icp_relevance": 2,
        "evidence_correctness": "UNSUPPORTED",
        "signal_relevance": 0,
        "brief_usefulness": 0,
        "evidence_links_working": True,
        "unsupported_important_claim": True,
        "notes": (
            "Official HROne subdomain, but hrone.cloud is the canonical company domain. "
            "The attached Go robotaxi IPO was a wrong-entity signal and 4,832 employees "
            "was UI mock data, not HROne workforce evidence."
        ),
    },
    "bharatbuild.ai": {
        "company_validity": "REAL",
        "domain_correctness": "CORRECT",
        "icp_relevance": 1,
        "evidence_correctness": "PARTIAL",
        "signal_relevance": 0,
        "brief_usefulness": 1,
        "evidence_links_working": True,
        "unsupported_important_claim": True,
        "notes": (
            "Real India AI development product, but the 50-500 employee target is not "
            "supported by first-party evidence and the product is not a strong support-scaleup fit."
        ),
    },
    "gaintrace.com": {
        "company_validity": "REAL",
        "domain_correctness": "CORRECT",
        "icp_relevance": 1,
        "evidence_correctness": "PARTIAL",
        "signal_relevance": 0,
        "brief_usefulness": 1,
        "evidence_links_working": True,
        "unsupported_important_claim": False,
        "notes": (
            "Real early-access customer-success platform with support-adjacent operations, "
            "but no verified 50-500 employee fit or current buying trigger."
        ),
    },
    "biggerwide.com": {
        "company_validity": "REAL",
        "domain_correctness": "CORRECT",
        "icp_relevance": 1,
        "evidence_correctness": "PARTIAL",
        "signal_relevance": 0,
        "brief_usefulness": 1,
        "evidence_links_working": True,
        "unsupported_important_claim": False,
        "notes": (
            "Real India transport broker SaaS, but visibly early-stage and outside the "
            "preferred company-size evidence gate."
        ),
    },
    "complydp.com": {
        "company_validity": "REAL",
        "domain_correctness": "CORRECT",
        "icp_relevance": 1,
        "evidence_correctness": "PARTIAL",
        "signal_relevance": 0,
        "brief_usefulness": 1,
        "evidence_links_working": True,
        "unsupported_important_claim": True,
        "notes": (
            "Real India DPDP software and services product. The earlier 100+ employee "
            "classification was not reproduced by conservative first-party extraction."
        ),
    },
    "zeeks.in": {
        "company_validity": "REAL",
        "domain_correctness": "CORRECT",
        "icp_relevance": 1,
        "evidence_correctness": "SUPPORTED",
        "signal_relevance": 0,
        "brief_usefulness": 1,
        "evidence_links_working": True,
        "unsupported_important_claim": False,
        "notes": (
            "Real India consent-management SaaS with correct first-party evidence, "
            "but company size and support-scale trigger remain unknown."
        ),
    },
    "saasoty.com": {
        "company_validity": "REAL",
        "domain_correctness": "CORRECT",
        "icp_relevance": 1,
        "evidence_correctness": "PARTIAL",
        "signal_relevance": 0,
        "brief_usefulness": 1,
        "evidence_links_working": True,
        "unsupported_important_claim": False,
        "notes": (
            "Real enterprise procurement product associated with Fineshift. Evidence "
            "included social sources and did not establish the selected 50-500 employee ICP."
        ),
    },
    "asintellect.com": {
        "company_validity": "REAL",
        "domain_correctness": "CORRECT",
        "icp_relevance": 1,
        "evidence_correctness": "PARTIAL",
        "signal_relevance": 0,
        "brief_usefulness": 1,
        "evidence_links_working": True,
        "unsupported_important_claim": False,
        "notes": (
            "Real early-access Amazon seller analytics product. Unrelated Amazon-product "
            "pages entered the source set, although no intent claim was generated from them."
        ),
    },
    "optivian.cloud": {
        "company_validity": "REAL",
        "domain_correctness": "CORRECT",
        "icp_relevance": 1,
        "evidence_correctness": "SUPPORTED",
        "signal_relevance": 0,
        "brief_usefulness": 1,
        "evidence_links_working": True,
        "unsupported_important_claim": False,
        "notes": (
            "Real India-first hosting platform with correct first-party evidence, but "
            "company size and a current support-automation trigger remain unknown."
        ),
    },
    "foresiet.com": {
        "company_validity": "REAL",
        "domain_correctness": "CORRECT",
        "icp_relevance": 2,
        "evidence_correctness": "SUPPORTED",
        "signal_relevance": 0,
        "brief_usefulness": 2,
        "evidence_links_working": True,
        "unsupported_important_claim": False,
        "notes": (
            "Real India cybersecurity SaaS with the strongest operating evidence in the "
            "set, but no verified current buying trigger and no first-party employee band."
        ),
    },
}


async def main() -> None:
    async with SessionFactory() as session:
        run = await session.get(ResearchRunRow, RUN_ID)
        if run is None:
            raise SystemExit(f"Research run not found: {RUN_ID}")
        accounts = list(
            (
                await session.scalars(
                    select(AccountRow).where(
                        AccountRow.workspace_id == run.workspace_id,
                        AccountRow.domain.in_(EVALUATIONS),
                    )
                )
            ).all()
        )
        by_domain = {item.domain: item for item in accounts}
        missing = sorted(set(EVALUATIONS) - set(by_domain))
        if missing:
            raise SystemExit(f"QA accounts not found: {', '.join(missing)}")

        created = 0
        for domain, values in EVALUATIONS.items():
            account = by_domain[domain]
            exists = await session.scalar(
                select(QAEvaluationRow.id).where(
                    QAEvaluationRow.research_run_id == RUN_ID,
                    QAEvaluationRow.account_id == account.id,
                    QAEvaluationRow.evaluator_id == EVALUATOR,
                )
            )
            if exists is not None:
                continue
            payload = QAEvaluationInput(
                research_run_id=str(RUN_ID),
                account_id=str(account.id),
                **values,  # type: ignore[arg-type]
            )
            await repository.create_qa_evaluation(
                session,
                str(run.workspace_id),
                EVALUATOR,
                payload,
            )
            created += 1
        print(f"Persisted {created} new manual QA evaluations; total target=10")


if __name__ == "__main__":
    asyncio.run(main())
