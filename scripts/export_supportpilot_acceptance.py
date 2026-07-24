from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID

from sqlalchemy import desc, select

from apps.api.app.db.models import (
    AccountRow,
    ICPProfileRow,
    ProductProfileRow,
    ResearchRunRow,
    ResearchTaskRow,
)
from apps.api.app.db.session import SessionFactory
from apps.api.app.repositories.postgres import repository


async def main() -> None:
    async with SessionFactory() as session:
        product_query = select(ProductProfileRow).where(
            ProductProfileRow.company_name == "SupportPilot AI"
        )
        workspace_id = os.getenv("SUPPORTPILOT_EXPORT_WORKSPACE")
        if workspace_id:
            product_query = product_query.where(
                ProductProfileRow.workspace_id == UUID(workspace_id)
            )
        product = await session.scalar(
            product_query.order_by(desc(ProductProfileRow.created_at)).limit(1)
        )
        if product is None:
            raise SystemExit("SupportPilot AI product not found")
        run = await session.scalar(
            select(ResearchRunRow)
            .where(ResearchRunRow.product_id == product.id)
            .order_by(desc(ResearchRunRow.created_at))
            .limit(1)
        )
        if run is None:
            raise SystemExit("SupportPilot AI research run not found")
        icp_rows = list(
            (
                await session.scalars(
                    select(ICPProfileRow)
                    .where(ICPProfileRow.research_run_id == run.id)
                    .order_by(ICPProfileRow.created_at)
                )
            ).all()
        )
        account_rows = list(
            (
                await session.scalars(
                    select(AccountRow)
                    .where(AccountRow.workspace_id == product.workspace_id)
                    .order_by(desc(AccountRow.last_researched_at))
                )
            ).all()
        )
        accounts = []
        briefs = []
        for row in account_rows:
            account = await repository.account_domain(session, row)
            if account is None:
                continue
            accounts.append(account)
        accounts.sort(key=lambda item: item.scores.priority, reverse=True)
        for account in accounts[:10]:
            brief = await repository.brief(
                session, str(product.workspace_id), account.id
            )
            if brief is not None:
                briefs.append(brief)
        tasks = list(
            (
                await session.scalars(
                    select(ResearchTaskRow)
                    .where(ResearchTaskRow.research_run_id == run.id)
                    .order_by(ResearchTaskRow.created_at)
                )
            ).all()
        )
        result = {
            "test_product_label": ("TEST PRODUCT PROFILE - NOT A REAL COMPANY CLAIM"),
            "workspace_id": str(product.workspace_id),
            "product": repository.product_domain(product).model_dump(mode="json"),
            "research_run": (await repository.run_domain(session, run)).model_dump(
                mode="json"
            ),
            "icps": [
                repository.icp_domain(item).model_dump(mode="json") for item in icp_rows
            ],
            "accounts": [item.model_dump(mode="json") for item in accounts],
            "top_briefs": [item.model_dump(mode="json") for item in briefs],
            "research_tasks": [
                {
                    "task_type": item.task_type,
                    "query": item.query,
                    "status": item.status,
                    "source_strategy": item.source_strategy,
                    "result_summary": item.result_summary,
                    "error": item.error,
                }
                for item in tasks
            ],
        }
    output = Path(
        os.getenv(
            "SUPPORTPILOT_EXPORT_PATH",
            "tmp/supportpilot-acceptance/normalized_result.json",
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "path": str(output.resolve()),
                "accounts": len(result["accounts"]),
                "briefs": len(result["top_briefs"]),
            }
        )
    )
    for index, account in enumerate(result["accounts"], 1):
        assert isinstance(account, dict)
        scores = account["scores"]
        assert isinstance(scores, dict)
        print(
            f"{index:02d} | {scores['priority']:3} | "
            f"{account['qualification_status']:21} | "
            f"{account['domain']:24} | {str(account['name'])[:70]} | "
            f"{account.get('top_signal_type') or 'NO_SIGNAL'}"
        )


if __name__ == "__main__":
    asyncio.run(main())
