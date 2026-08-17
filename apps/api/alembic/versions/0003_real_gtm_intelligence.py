"""add real GTM intelligence feedback primitives

Revision ID: 0003_real_gtm_intelligence
Revises: 0002_live_intelligence
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0003_real_gtm_intelligence"
down_revision: str | None = "0002_live_intelligence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feedback_events",
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=128), nullable=False),
        sa.Column("rating", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_feedback_events_workspace_id",
        "feedback_events",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_feedback_events_target_type",
        "feedback_events",
        ["target_type"],
        unique=False,
    )
    op.create_index(
        "ix_feedback_events_target_id",
        "feedback_events",
        ["target_id"],
        unique=False,
    )
    op.create_index(
        "ix_feedback_events_rating",
        "feedback_events",
        ["rating"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_feedback_events_rating", table_name="feedback_events")
    op.drop_index("ix_feedback_events_target_id", table_name="feedback_events")
    op.drop_index("ix_feedback_events_target_type", table_name="feedback_events")
    op.drop_index("ix_feedback_events_workspace_id", table_name="feedback_events")
    op.drop_table("feedback_events")
