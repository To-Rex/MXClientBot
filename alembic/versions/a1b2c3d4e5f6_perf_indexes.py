"""perf indexes for hot lookups

Revision ID: a1b2c3d4e5f6
Revises: 4658d13c1436
Create Date: 2026-08-17
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '4658d13c1436'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_users_bot_id_telegram_id', 'users', ['bot_id', 'telegram_id'], unique=False, if_not_exists=True)
    op.create_index('ix_web_sessions_bot_id_telegram_id', 'web_sessions', ['bot_id', 'telegram_id'], unique=False, if_not_exists=True)
    op.create_index('ix_cart_items_bot_id_telegram_id_product_id', 'cart_items', ['bot_id', 'telegram_id', 'product_id'], unique=False, if_not_exists=True)


def downgrade() -> None:
    op.drop_index('ix_cart_items_bot_id_telegram_id_product_id', table_name='cart_items', if_exists=True)
    op.drop_index('ix_web_sessions_bot_id_telegram_id', table_name='web_sessions', if_exists=True)
    op.drop_index('ix_users_bot_id_telegram_id', table_name='users', if_exists=True)
