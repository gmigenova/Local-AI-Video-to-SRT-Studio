"""translation_usage table (Google Cloud Translation metering)

Revision ID: d7c2f8a4b1e6
Revises: b3e6a1f5c2d9
Create Date: 2026-11-11 18:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd7c2f8a4b1e6'
down_revision: str | None = 'b3e6a1f5c2d9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'translation_usage',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('period', sa.String(length=7), nullable=False),
        sa.Column('characters_sent', sa.BigInteger(), nullable=False),
        sa.Column('words_sent', sa.BigInteger(), nullable=False),
        sa.Column('texts_translated', sa.Integer(), nullable=False),
        sa.Column('requests', sa.Integer(), nullable=False),
        sa.Column('jobs', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_translation_usage_period', 'translation_usage', ['period'], unique=True
    )


def downgrade() -> None:
    op.drop_index('ix_translation_usage_period', table_name='translation_usage')
    op.drop_table('translation_usage')
