"""add municipio, uf, cep to entregas

Revision ID: f1a2b3c4d5e6
Revises: d1e2f3a4b5c6
Create Date: 2026-05-29

"""
from alembic import op
import sqlalchemy as sa

revision = 'f1a2b3c4d5e6'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('entregas', sa.Column('municipio', sa.String(100), nullable=True))
    op.add_column('entregas', sa.Column('uf',        sa.String(2),   nullable=True))
    op.add_column('entregas', sa.Column('cep',       sa.String(10),  nullable=True))


def downgrade():
    op.drop_column('entregas', 'cep')
    op.drop_column('entregas', 'uf')
    op.drop_column('entregas', 'municipio')
