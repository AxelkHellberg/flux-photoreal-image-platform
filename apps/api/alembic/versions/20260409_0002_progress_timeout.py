"""add last_progress_at

Revision ID: 20260409_0002
Revises: 20260409_0001
Create Date: 2026-04-09 22:35:00

"""

import sqlalchemy as sa
from alembic import op

revision = "20260409_0002"
down_revision = "20260409_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("image_jobs", sa.Column("last_progress_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_image_jobs_last_progress_at"), "image_jobs", ["last_progress_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_image_jobs_last_progress_at"), table_name="image_jobs")
    op.drop_column("image_jobs", "last_progress_at")
