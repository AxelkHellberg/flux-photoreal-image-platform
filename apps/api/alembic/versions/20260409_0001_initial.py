"""initial schema

Revision ID: 20260409_0001
Revises:
Create Date: 2026-04-09 14:00:00

"""

import sqlalchemy as sa
from alembic import op

revision = "20260409_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "image_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("prompt_original", sa.Text(), nullable=False),
        sa.Column("prompt_final", sa.Text(), nullable=False),
        sa.Column("negative_prompt", sa.Text(), nullable=False),
        sa.Column("aspect_ratio", sa.String(length=16), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("auto_enhance_prompt", sa.Boolean(), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("progress_stage", sa.String(length=64), nullable=False),
        sa.Column("generation_params", sa.JSON(), nullable=False),
        sa.Column("storage_bucket", sa.String(length=255), nullable=True),
        sa.Column("storage_key", sa.String(length=1024), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retried_from_job_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["retried_from_job_id"], ["image_jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_image_jobs_status"), "image_jobs", ["status"], unique=False)
    op.create_index(op.f("ix_image_jobs_created_at"), "image_jobs", ["created_at"], unique=False)
    op.create_index(op.f("ix_image_jobs_heartbeat_at"), "image_jobs", ["heartbeat_at"], unique=False)
    op.create_index(op.f("ix_image_jobs_lease_token"), "image_jobs", ["lease_token"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_image_jobs_lease_token"), table_name="image_jobs")
    op.drop_index(op.f("ix_image_jobs_heartbeat_at"), table_name="image_jobs")
    op.drop_index(op.f("ix_image_jobs_created_at"), table_name="image_jobs")
    op.drop_index(op.f("ix_image_jobs_status"), table_name="image_jobs")
    op.drop_table("image_jobs")
