"""add_chat_and_msg_to_poll_mapping

Revision ID: a1b2c3d4e5f6
Revises: 7a3ea1cb26bb
Create Date: 2026-07-06 10:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'fcc1d8034480'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('poll_mappings', sa.Column('chat_id', sa.String(length=256), nullable=True))
    op.add_column('poll_mappings', sa.Column('message_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('poll_mappings', 'message_id')
    op.drop_column('poll_mappings', 'chat_id')
