"""opening and closing stock counts for a shift

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-30 12:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    postgresql.ENUM("count", "opening", "closing", name="stock_take_kind").create(op.get_bind())
    # Stock takes are permanent; adding columns doesn't touch their rows' trigger.
    op.add_column('stock_takes', sa.Column('kind', postgresql.ENUM(name='stock_take_kind', create_type=False),
                                           server_default='count', nullable=False))
    op.add_column('stock_takes', sa.Column('shift_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_stock_takes_shift_id'), 'stock_takes', ['shift_id'], unique=False)
    op.create_foreign_key(op.f('fk_stock_takes_shift_id_shifts'), 'stock_takes', 'shifts', ['shift_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint(op.f('fk_stock_takes_shift_id_shifts'), 'stock_takes', type_='foreignkey')
    op.drop_index(op.f('ix_stock_takes_shift_id'), table_name='stock_takes')
    op.drop_column('stock_takes', 'shift_id')
    op.drop_column('stock_takes', 'kind')
    postgresql.ENUM(name="stock_take_kind").drop(op.get_bind())
