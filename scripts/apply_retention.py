"""Report, and optionally delete, research data past the retention window.

Deliberately **not** automatic and **not** scheduled. This is data a paying
customer would be upset to lose silently, so the destructive path is opt-in twice:
once by running this command at all, and again with --confirm after reading the
preview.

    python scripts/apply_retention.py                      # preview everything
    python scripts/apply_retention.py --workspace-id <id>  # preview one workspace
    python scripts/apply_retention.py --workspace-id <id> --confirm

The window comes from RESEARCH_RETENTION_DAYS. Accounts, briefs and review history
are never touched: the window applies to retrieved source documents and the evidence
derived from them, which is the material with a real staleness cost. A founder's own
imported list and their review decisions are theirs until they delete the workspace.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, ".")

from apps.api.app.config import settings  # noqa: E402
from apps.api.app.db.models import (  # noqa: E402
    EvidenceFactRow,
    SourceDocumentRow,
    WorkspaceRow,
)
from apps.api.app.db.session import SessionFactory  # noqa: E402


async def _expired_sources(
    session: AsyncSession, cutoff: datetime, workspace: uuid.UUID | None
) -> list[SourceDocumentRow]:
    statement = select(SourceDocumentRow).where(
        SourceDocumentRow.retrieved_at < cutoff
    )
    if workspace is not None:
        statement = statement.where(SourceDocumentRow.workspace_id == workspace)
    return list((await session.scalars(statement)).all())


async def run(args: argparse.Namespace) -> int:
    workspace = uuid.UUID(args.workspace_id) if args.workspace_id else None
    cutoff = datetime.now(UTC) - timedelta(days=settings.research_retention_days)

    print(f"Retention window: {settings.research_retention_days} days")
    print(f"Cutoff:           {cutoff.isoformat()}")
    print(f"Scope:            {workspace or 'all workspaces'}\n")

    async with SessionFactory() as session:
        if workspace is not None and await session.get(WorkspaceRow, workspace) is None:
            raise SystemExit(f"Workspace {workspace} does not exist")

        sources = await _expired_sources(session, cutoff, workspace)
        if not sources:
            print("Nothing is past the retention window.")
            return 0

        source_ids = [item.id for item in sources]
        facts = int(
            await session.scalar(
                select(func.count())
                .select_from(EvidenceFactRow)
                .where(EvidenceFactRow.source_id.in_(source_ids))
            )
            or 0
        )

        by_workspace: dict[uuid.UUID, int] = {}
        oldest = min(item.retrieved_at for item in sources)
        for item in sources:
            by_workspace[item.workspace_id] = by_workspace.get(item.workspace_id, 0) + 1

        print(f"Eligible source documents: {len(sources)}")
        print(f"Evidence facts derived:    {facts}")
        print(f"Oldest retrieval:          {oldest.isoformat()}")
        print("Per workspace:")
        for ws, count in sorted(by_workspace.items(), key=lambda item: -item[1]):
            print(f"  {ws}  {count}")
        print("\nAccounts, briefs and review history are not affected.")

        if not args.confirm:
            print("\nPREVIEW ONLY. Nothing was deleted.")
            print("Re-run with --confirm to delete the documents listed above.")
            return 0

        # Facts cascade from their source document.
        await session.execute(
            delete(SourceDocumentRow).where(SourceDocumentRow.id.in_(source_ids))
        )
        await session.commit()
        print(f"\nDeleted {len(sources)} source documents and {facts} evidence facts.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", help="limit to one workspace")
    parser.add_argument(
        "--confirm", action="store_true", help="actually delete; previews without it"
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
