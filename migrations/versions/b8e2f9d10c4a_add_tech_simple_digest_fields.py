"""add tech and simple digest fields to posts and digests

Revision ID: b8e2f9d10c4a
Revises: d59f4df00ba2
Create Date: 2026-08-07 15:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b8e2f9d10c4a'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('digests', sa.Column('digest_type', sa.String(length=50), server_default='tech', nullable=False))

    op.add_column('posts', sa.Column('tech_digest_id', sa.Integer(), nullable=True))
    op.add_column('posts', sa.Column('simple_digest_id', sa.Integer(), nullable=True))
    op.add_column('posts', sa.Column('is_tech_relevant', sa.Boolean(), nullable=True))
    op.add_column('posts', sa.Column('is_simple_relevant', sa.Boolean(), nullable=True))

    op.add_column('posts', sa.Column('tech_facts', postgresql.JSON(astext_type=sa.Text()).with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), server_default='[]', nullable=False))
    op.add_column('posts', sa.Column('simple_facts', postgresql.JSON(astext_type=sa.Text()).with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), server_default='[]', nullable=False))
    op.add_column('posts', sa.Column('tech_questions', postgresql.JSON(astext_type=sa.Text()).with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), server_default='[]', nullable=False))
    op.add_column('posts', sa.Column('simple_questions', postgresql.JSON(astext_type=sa.Text()).with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), server_default='[]', nullable=False))

    op.create_foreign_key('fk_posts_tech_digest_id_digests', 'posts', 'digests', ['tech_digest_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_posts_simple_digest_id_digests', 'posts', 'digests', ['simple_digest_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_posts_simple_digest_id_digests', 'posts', type_='foreignkey')
    op.drop_constraint('fk_posts_tech_digest_id_digests', 'posts', type_='foreignkey')

    op.drop_column('posts', 'simple_questions')
    op.drop_column('posts', 'tech_questions')
    op.drop_column('posts', 'simple_facts')
    op.drop_column('posts', 'tech_facts')
    op.drop_column('posts', 'is_simple_relevant')
    op.drop_column('posts', 'is_tech_relevant')
    op.drop_column('posts', 'simple_digest_id')
    op.drop_column('posts', 'tech_digest_id')

    op.drop_column('digests', 'digest_type')
