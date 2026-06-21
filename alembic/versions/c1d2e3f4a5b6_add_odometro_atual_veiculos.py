"""add odometro_atual to veiculos

Revision ID: c1d2e3f4a5b6
Revises: b2c3d4e5f6a7
Create Date: 2026-06-07

"""
from alembic import op
import sqlalchemy as sa

revision = 'c1d2e3f4a5b6'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'veiculos',
        sa.Column('odometro_atual', sa.Integer(), nullable=True)
    )


def downgrade():
    op.drop_column('veiculos', 'odometro_atual')
