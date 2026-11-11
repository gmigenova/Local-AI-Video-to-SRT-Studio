"""video_renders table (subtitle burn-in renders)

Revision ID: a1c4f7e2b9d8
Revises: 58b722e639c3
Create Date: 2026-11-11 10:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1c4f7e2b9d8'
down_revision: str | None = '58b722e639c3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('video_renders',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('job_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('progress', sa.Float(), nullable=False),
    sa.Column('current_stage', sa.String(length=100), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('font_name', sa.String(length=100), nullable=True),
    sa.Column('output_path', sa.Text(), nullable=True),
    sa.Column('file_size', sa.BigInteger(), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['transcription_jobs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('video_renders', schema=None) as batch_op:
        batch_op.create_index('ix_video_renders_job_id', ['job_id'], unique=False)
        batch_op.create_index('ix_video_renders_status', ['status'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('video_renders', schema=None) as batch_op:
        batch_op.drop_index('ix_video_renders_status', unique=False)
        batch_op.drop_index('ix_video_renders_job_id', unique=False)
    op.drop_table('video_renders')
