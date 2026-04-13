"""normalize legacy generation modes to photoreal

Revision ID: 20260410_0003
Revises: 20260409_0002
Create Date: 2026-04-10 16:30:00

"""

from alembic import op

revision = "20260410_0003"
down_revision = "20260409_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE image_jobs SET mode = 'photoreal' WHERE mode IN ('fast', 'quality')")


def downgrade() -> None:
    pass
