"""video_renders.source column (editor vs external srt)

Revision ID: b3e6a1f5c2d9
Revises: a1c4f7e2b9d8
Create Date: 2026-11-11 12:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b3e6a1f5c2d9'
down_revision: str | None = 'a1c4f7e2b9d8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('video_renders', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('source', sa.String(length=20), nullable=False,
                      server_default='editor')
        )


def downgrade() -> None:
    with op.batch_alter_table('video_renders', schema=None) as batch_op:
        batch_op.drop_column('source')
