"""question_stimuli gains a figure kind and an asset_key for diagram images

Revision ID: 9f3e6b1c2a4d
Revises: 742b0c9e2566
Create Date: 2026-08-26 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '9f3e6b1c2a4d'
down_revision: str | None = '742b0c9e2566'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Postgres allows ADD VALUE inside a transaction but forbids *using* the new value
    # in that same transaction. Nothing below inserts one, so this is safe here.
    op.execute("ALTER TYPE stimulus_kind ADD VALUE IF NOT EXISTS 'figure'")
    op.add_column(
        'question_stimuli', sa.Column('asset_key', sa.String(length=255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('question_stimuli', 'asset_key')
    # Postgres has no ALTER TYPE ... DROP VALUE; a downgrade would need to rebuild the
    # enum from scratch (create new type, cast every column, drop old, rename), which
    # is destructive for a value that may already be in use. Left as-is, matching the
    # standing convention of not reversing additive enum values in this codebase.
