"""add origem to entregas

Revision ID: 2b3c4d5e6f7a
Revises: 1a2b3c4d5e6f
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa

revision = '2b3c4d5e6f7a'
down_revision = '1a2b3c4d5e6f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('entregas',
        sa.Column('origem', sa.String(20), nullable=False, server_default='pdv')
    )


def downgrade():
    op.drop_column('entregas', 'origem')
