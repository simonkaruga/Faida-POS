"""orders by number, with an optional typed table

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-16 12:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A table typed on the keypad ("57", "S12") that isn't set up in Tables & sections.
    op.add_column("bills", sa.Column("table_label", sa.String(length=30), nullable=True))


def downgrade() -> None:
    op.drop_column("bills", "table_label")
