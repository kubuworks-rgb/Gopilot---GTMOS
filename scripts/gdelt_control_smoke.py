from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from apps.api.app.config import settings
from apps.api.app.db.session import SessionFactory
from apps.api.app.repositories.postgres import repository
from apps.api.app.services.live_research import execute_research


CONTROL_QUERY = '"OpenAI"'


async def main() -> None:
    suffix = int(datetime.now(UTC).timestamp())
    user_id = f"gdelt-control-{suffix}"
    async with SessionFactory() as session:
        workspace = await repository.create_workspace(
            session,
            user_id,
            "GDELT Known-Positive Control",
        )
        product = await repository.create_product(
            session,
            workspace.id,
            user_id,
            company_name="OpenAI Public Control",
            website="https://openai.com",
            product="OpenAI",
            target_market="OpenAI",
        )
        run = await repository.create_run(
            session,
            workspace.id,
            user_id,
            product.id,
            {
                "max_searches": 1,
                "max_documents": settings.max_research_documents,
                "max_elapsed_seconds": settings.max_elapsed_seconds,
                "diagnostic_control": True,
            },
        )

    await execute_research(run.id, queries_override=[CONTROL_QUERY])

    async with SessionFactory() as session:
        row = await repository.run_row(session, run.id, workspace.id)
        if row is None:
            raise RuntimeError("Control run was not persisted")
        domain = await repository.run_domain(session, row)
        print(
            json.dumps(
                {
                    "query": CONTROL_QUERY,
                    "workspace_id": workspace.id,
                    "user_id": user_id,
                    "research_run_id": run.id,
                    "status": domain.status,
                    "current_stage": domain.current_stage,
                    "searches_used": domain.searches_used,
                    "documents_used": domain.documents_used,
                    "findings": len(domain.findings),
                    "error": domain.error,
                },
                indent=2,
                default=str,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
