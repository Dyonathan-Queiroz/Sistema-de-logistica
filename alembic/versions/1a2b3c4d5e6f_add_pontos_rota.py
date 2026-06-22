"""add tabela pontos_rota para rastreamento GPS de entregas

Revision ID: 1a2b3c4d5e6f
Revises: e4f5a6b7c8d9
Create Date: 2026-06-22

"""
from alembic import op
import sqlalchemy as sa

revision = '1a2b3c4d5e6f'
down_revision = 'e4f5a6b7c8d9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'pontos_rota',
        sa.Column('id',         sa.Integer(),     nullable=False),
        sa.Column('entrega_id', sa.Integer(),     nullable=False),
        sa.Column('latitude',   sa.Float(),       nullable=False),
        sa.Column('longitude',  sa.Float(),       nullable=False),
        sa.Column('timestamp',  sa.DateTime(),    nullable=True),
        sa.Column('tipo',       sa.String(12),    nullable=True),
        sa.ForeignKeyConstraint(['entrega_id'], ['entregas.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_pontos_rota_entrega_id', 'pontos_rota', ['entrega_id'])


def downgrade():
    op.drop_index('ix_pontos_rota_entrega_id', table_name='pontos_rota')
    op.drop_table('pontos_rota')
