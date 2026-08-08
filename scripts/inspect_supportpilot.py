from __future__ import annotations

import asyncio
import json

from sqlalchemy import text

from apps.api.app.db.session import SessionFactory


async def main() -> None:
    async with SessionFactory() as session:
        runs = (
            (
                await session.execute(
                    text(
                        """
                    select w.id as workspace_id, w.name, m.user_id, r.id as run_id,
                           r.status, r.current_stage, p.id as product_id,
                           p.company_name
                    from workspaces w
                    join product_profiles p on p.workspace_id = w.id
                    join research_runs r on r.product_id = p.id
                    join memberships m on m.workspace_id = w.id
                    where p.company_name = :company
                    order by r.created_at desc
                    limit 3
                    """
                    ),
                    {"company": "SupportPilot AI"},
                )
            )
            .mappings()
            .all()
        )
        print(json.dumps([dict(item) for item in runs], default=str))
        if not runs:
            return
        icps = (
            (
                await session.execute(
                    text(
                        """
                    select id, workspace_id, research_run_id, name, definition
                    from icp_profiles
                    where research_run_id = :run_id
                    order by created_at
                    """
                    ),
                    {"run_id": runs[0]["run_id"]},
                )
            )
            .mappings()
            .all()
        )
        print(json.dumps([dict(item) for item in icps], default=str))


if __name__ == "__main__":
    asyncio.run(main())
