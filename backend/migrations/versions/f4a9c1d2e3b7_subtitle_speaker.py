"""subtitles.speaker column (diarization labels)

Revision ID: f4a9c1d2e3b7
Revises: c8d3e5f7a9b1
Create Date: 2026-11-14 13:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f4a9c1d2e3b7'
down_revision: str | None = 'c8d3e5f7a9b1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('subtitles', schema=None) as batch_op:
        batch_op.add_column(sa.Column('speaker', sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('subtitles', schema=None) as batch_op:
        batch_op.drop_column('speaker')
