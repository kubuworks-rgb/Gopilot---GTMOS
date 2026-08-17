"""Invite-only access and bounded usage for the private alpha.

Two rules run through everything here:

* Limits return an explicit error. Nothing is silently truncated, because a caller
  who imported 300 accounts and received 100 without being told has been given a
  wrong answer, not a partial one.
* Access decisions fail closed. When the invite list cannot admit someone, they are
  refused rather than admitted by default.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.config import Settings, settings
from apps.api.app.db.models import (
    AccountRow,
    AuditEventRow,
    MembershipRow,
    ResearchRunRow,
)


ACTIVE_RUN_STATUSES = (
    "queued",
    "planning",
    "researching",
    "extracting",
    "awaiting_icp",
    "discovering_accounts",
    "scoring",
)

IMPORT_EVENT = "account_imported"


class AccessDenied(Exception):
    """The caller is not invited to the private alpha."""


@dataclass(frozen=True)
class LimitExceeded(Exception):
    """A configured private-alpha limit would be exceeded by this request."""

    code: str
    message: str
    limit: int
    attempted: int

    def as_detail(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "limit": self.limit,
            "attempted": self.attempted,
        }


def retention_policy(config: Settings | None = None) -> dict[str, object]:
    """The retention statement shown on Settings.

    Defined once and served by both routers, so what a user reads cannot drift from
    what an operator configured.
    """

    config = config or settings
    return {
        "research_retention_days": config.research_retention_days,
        "automatic_deletion": config.retention_auto_delete,
        "summary": (
            "Retrieved pages and the evidence derived from them are kept for "
            f"{config.research_retention_days} days, after which they become "
            "eligible for deletion. Your accounts, briefs and review notes are kept "
            "until you delete them. Nothing is deleted automatically."
        ),
    }


def assert_invited(
    subject: str, email: str | None = None, config: Settings | None = None
) -> None:
    """Admit only explicitly invited identities while the private alpha is on."""

    config = config or settings
    if not config.private_alpha_enabled:
        return
    if subject in config.private_alpha_allowed_subjects:
        return
    if email and email.strip().lower() in config.private_alpha_allowed_emails:
        return
    raise AccessDenied("This deployment is invite-only during the private alpha")


def experimental_discovery_allowed(config: Settings | None = None) -> bool:
    """Discovery stays off by default in the private alpha, provider or not."""

    config = config or settings
    if config.private_alpha_enabled and not config.allow_experimental_discovery:
        return False
    return True


def assert_import_size(count: int, config: Settings | None = None) -> None:
    config = config or settings
    if count > config.max_accounts_per_import:
        raise LimitExceeded(
            code="IMPORT_TOO_LARGE",
            message=(
                f"Import at most {config.max_accounts_per_import} accounts at a time. "
                "Nothing was imported; split the file and retry."
            ),
            limit=config.max_accounts_per_import,
            attempted=count,
        )


async def assert_workspace_capacity(
    session: AsyncSession,
    workspace_id: str,
    incoming: int,
    config: Settings | None = None,
) -> None:
    config = config or settings
    existing = int(
        await session.scalar(
            select(func.count())
            .select_from(AccountRow)
            .where(AccountRow.workspace_id == uuid.UUID(workspace_id))
        )
        or 0
    )
    if existing + incoming > config.max_accounts_per_workspace:
        raise LimitExceeded(
            code="WORKSPACE_ACCOUNT_LIMIT",
            message=(
                f"This workspace holds {existing} of "
                f"{config.max_accounts_per_workspace} accounts during the private "
                f"alpha, so {incoming} more cannot be added. Nothing was imported."
            ),
            limit=config.max_accounts_per_workspace,
            attempted=existing + incoming,
        )


async def assert_daily_import_quota(
    session: AsyncSession, workspace_id: str, config: Settings | None = None
) -> None:
    config = config or settings
    since = datetime.now(UTC) - timedelta(days=1)
    used = int(
        await session.scalar(
            select(func.count())
            .select_from(AuditEventRow)
            .where(
                AuditEventRow.workspace_id == uuid.UUID(workspace_id),
                AuditEventRow.event_type == IMPORT_EVENT,
                AuditEventRow.created_at >= since,
            )
        )
        or 0
    )
    if used >= config.max_imports_per_day:
        raise LimitExceeded(
            code="DAILY_IMPORT_LIMIT",
            message=(
                f"This workspace reached its {config.max_imports_per_day} imports "
                "per day during the private alpha. Try again tomorrow."
            ),
            limit=config.max_imports_per_day,
            attempted=used + 1,
        )


async def assert_run_concurrency(
    session: AsyncSession, workspace_id: str, config: Settings | None = None
) -> None:
    config = config or settings
    active = int(
        await session.scalar(
            select(func.count())
            .select_from(ResearchRunRow)
            .where(
                ResearchRunRow.workspace_id == uuid.UUID(workspace_id),
                ResearchRunRow.status.in_(ACTIVE_RUN_STATUSES),
            )
        )
        or 0
    )
    if active >= config.max_concurrent_research_runs:
        raise LimitExceeded(
            code="CONCURRENT_RUN_LIMIT",
            message=(
                f"{active} research runs are already in progress "
                f"(limit {config.max_concurrent_research_runs}). "
                "Wait for one to finish."
            ),
            limit=config.max_concurrent_research_runs,
            attempted=active + 1,
        )


async def assert_workspace_quota(
    session: AsyncSession, user_id: str, config: Settings | None = None
) -> None:
    config = config or settings
    owned = int(
        await session.scalar(
            select(func.count())
            .select_from(MembershipRow)
            .where(MembershipRow.user_id == user_id)
        )
        or 0
    )
    if owned >= config.max_workspaces_per_user:
        raise LimitExceeded(
            code="WORKSPACE_LIMIT",
            message=(
                f"You already belong to {owned} workspaces "
                f"(limit {config.max_workspaces_per_user} during the private alpha)."
            ),
            limit=config.max_workspaces_per_user,
            attempted=owned + 1,
        )


def assert_export_size(count: int, config: Settings | None = None) -> None:
    """Refuse an oversized export rather than handing back a silently short file."""

    config = config or settings
    if count > config.max_export_rows:
        raise LimitExceeded(
            code="EXPORT_TOO_LARGE",
            message=(
                f"{count} approved accounts exceed the "
                f"{config.max_export_rows} row export limit. Narrow the selection; "
                "a truncated export would be misleading."
            ),
            limit=config.max_export_rows,
            attempted=count,
        )
