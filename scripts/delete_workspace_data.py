"""Tenant-scoped deletion for the private alpha.

Every query is filtered by workspace. There is no code path here that can reach
another tenant's rows, even if a caller supplies a matching account or run ID from
a different workspace -- those are verified to belong to the given workspace first.

Deletion is hard, not soft: when an operator tells a user their data is gone, it
is gone. `--dry-run` is the default so the destructive path is always opt-in.

Usage:
    python scripts/delete_workspace_data.py --workspace-id <uuid> --dry-run
    python scripts/delete_workspace_data.py --workspace-id <uuid> --account-id <uuid> --confirm
    python scripts/delete_workspace_data.py --workspace-id <uuid> --run-id <uuid> --confirm
    python scripts/delete_workspace_data.py --workspace-id <uuid> --confirm
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, ".")

from apps.api.app.db.models import (  # noqa: E402
    AccountRow,
    AuditEventRow,
    EvidenceFactRow,
    OpportunityBriefRow,
    ResearchRunRow,
    SourceDocumentRow,
    WorkspaceRow,
)
from apps.api.app.db.session import SessionFactory  # noqa: E402


async def _counts(session: AsyncSession, workspace: uuid.UUID) -> dict[str, int]:
    async def total(model: type) -> int:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.workspace_id == workspace)
            )
            or 0
        )

    return {
        "accounts": await total(AccountRow),
        "research_runs": await total(ResearchRunRow),
        "source_documents": await total(SourceDocumentRow),
        "evidence_facts": await total(EvidenceFactRow),
        "opportunity_briefs": await total(OpportunityBriefRow),
        "audit_events": await total(AuditEventRow),
    }


async def _assert_owned(
    session: AsyncSession, model: type, target: uuid.UUID, workspace: uuid.UUID
) -> None:
    row = await session.get(model, target)
    if row is None:
        raise SystemExit(f"{model.__name__} {target} does not exist")
    if row.workspace_id != workspace:
        # Never confirm or deny across a tenant boundary beyond this refusal.
        raise SystemExit("Target does not belong to the given workspace")


async def run(args: argparse.Namespace) -> int:
    workspace = uuid.UUID(args.workspace_id)

    async with SessionFactory() as session:
        if await session.get(WorkspaceRow, workspace) is None:
            raise SystemExit(f"Workspace {workspace} does not exist")

        before = await _counts(session, workspace)
        print(f"Workspace {workspace}")
        for name, value in before.items():
            print(f"  {name:20} {value}")

        if args.account_id:
            target = uuid.UUID(args.account_id)
            await _assert_owned(session, AccountRow, target, workspace)
            scope = f"account {target} and everything derived from it"
            statement = delete(AccountRow).where(
                AccountRow.id == target, AccountRow.workspace_id == workspace
            )
        elif args.run_id:
            target = uuid.UUID(args.run_id)
            await _assert_owned(session, ResearchRunRow, target, workspace)
            scope = f"research run {target} and its evidence"
            statement = delete(ResearchRunRow).where(
                ResearchRunRow.id == target,
                ResearchRunRow.workspace_id == workspace,
            )
        else:
            scope = "the entire workspace"
            statement = delete(WorkspaceRow).where(WorkspaceRow.id == workspace)

        if not args.confirm:
            print(f"\nDRY RUN. Would delete {scope}.")
            print("Re-run with --confirm to delete. Nothing was written.")
            return 0

        # Cascades from the parent row remove chunks, signals, scores, briefs,
        # drafts, approvals and audit rows.
        await session.execute(statement)
        await session.commit()
        print(f"\nDeleted {scope}.")

        if args.account_id or args.run_id:
            after = await _counts(session, workspace)
            print("Remaining:")
            for name, value in after.items():
                print(f"  {name:20} {value}")
        else:
            print("Workspace removed; no rows remain.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--account-id")
    parser.add_argument("--run-id")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="actually delete; without it the script only reports",
    )
    parser.add_argument("--dry-run", action="store_true", help="explicit no-op default")
    args = parser.parse_args()

    if args.account_id and args.run_id:
        raise SystemExit("Give --account-id or --run-id, not both")
    if args.confirm and args.dry_run:
        raise SystemExit("--confirm and --dry-run are mutually exclusive")

    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
