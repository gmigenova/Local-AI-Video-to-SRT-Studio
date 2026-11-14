"""video_renders subtitle_format + style_json (styled ASS burn-in)

Revision ID: c8d3e5f7a9b1
Revises: d7c2f8a4b1e6
Create Date: 2026-11-14 12:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c8d3e5f7a9b1'
down_revision: str | None = 'd7c2f8a4b1e6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('video_renders', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('subtitle_format', sa.String(length=10), nullable=False,
                      server_default='srt')
        )
        batch_op.add_column(sa.Column('style_json', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('video_renders', schema=None) as batch_op:
        batch_op.drop_column('style_json')
        batch_op.drop_column('subtitle_format')
