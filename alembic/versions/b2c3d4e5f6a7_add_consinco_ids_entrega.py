"""add nro_checkout, seq_docto, seq_pessoa to entregas

Revision ID: b2c3d4e5f6a7
Revises: f1a2b3c4d5e6
Create Date: 2026-05-29

"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6a7'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('entregas', sa.Column('nro_checkout', sa.Integer(), nullable=True))
    op.add_column('entregas', sa.Column('seq_docto',    sa.Integer(), nullable=True))
    op.add_column('entregas', sa.Column('seq_pessoa',   sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('entregas', 'seq_pessoa')
    op.drop_column('entregas', 'seq_docto')
    op.drop_column('entregas', 'nro_checkout')
