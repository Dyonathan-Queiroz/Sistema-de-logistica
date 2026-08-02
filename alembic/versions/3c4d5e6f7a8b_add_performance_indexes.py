"""add performance indexes on high-frequency filter columns

Revision ID: 3c4d5e6f7a8b
Revises: 2b3c4d5e6f7a
Create Date: 2026-07-21

Índices adicionados nesta migration:
  entregas.status           — filtrado em quase todas as rotas do sistema
  entregas.entregador_id    — filtrado em dashboard do entregador, log, desempenho
  entregas.filial_id        — filtrado em stats_filiais e log de entregas
  entregas.data_finalizacao — filtrado em consultas de entregas do dia
  turnos_entrega.status     — filtrado em _turno_aberto_hoje e frota_dashboard
  manutencoes.status        — filtrado em frota_manutencao e historico_geral
  manutencoes.categoria     — filtrado em frota_alertas e frota_analise

As colunas de aprovação (status, motorista_id, descricao_problema, observacao_gestor)
são verificadas via inspect() antes de adicionar — ADD COLUMN IF NOT EXISTS não existe
no MySQL (apenas MariaDB).
"""
import sqlalchemy as sa
from alembic import op

revision = '3c4d5e6f7a8b'
down_revision = '2b3c4d5e6f7a'
branch_labels = None
depends_on = None


def _cols(table: str) -> set:
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _idxs(table: str) -> set:
    return {i['name'] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    # Passo 1: colunas de aprovação em manutencoes (necessárias antes do índice status).
    mnt_cols = _cols('manutencoes')

    if 'status' not in mnt_cols:
        op.add_column('manutencoes', sa.Column(
            'status',
            sa.Enum('pendente', 'aprovada', 'rejeitada'),
            nullable=False,
            server_default='aprovada',
        ))

    if 'motorista_id' not in mnt_cols:
        op.add_column('manutencoes', sa.Column(
            'motorista_id', sa.Integer(), nullable=True,
        ))

    if 'descricao_problema' not in mnt_cols:
        op.add_column('manutencoes', sa.Column(
            'descricao_problema', sa.String(500), nullable=True,
        ))

    if 'observacao_gestor' not in mnt_cols:
        op.add_column('manutencoes', sa.Column(
            'observacao_gestor', sa.String(500), nullable=True,
        ))

    # Passo 2: índices de performance (CREATE INDEX IF NOT EXISTS é válido em MySQL 8.0+).
    ent_idxs = _idxs('entregas')
    if 'ix_entregas_status' not in ent_idxs:
        op.create_index('ix_entregas_status', 'entregas', ['status'])
    if 'ix_entregas_entregador_id' not in ent_idxs:
        op.create_index('ix_entregas_entregador_id', 'entregas', ['entregador_id'])
    if 'ix_entregas_filial_id' not in ent_idxs:
        op.create_index('ix_entregas_filial_id', 'entregas', ['filial_id'])
    if 'ix_entregas_data_finalizacao' not in ent_idxs:
        op.create_index('ix_entregas_data_finalizacao', 'entregas', ['data_finalizacao'])

    trn_idxs = _idxs('turnos_entrega')
    if 'ix_turno_status' not in trn_idxs:
        op.create_index('ix_turno_status', 'turnos_entrega', ['status'])

    mnt_idxs = _idxs('manutencoes')
    if 'ix_manutencoes_status' not in mnt_idxs:
        op.create_index('ix_manutencoes_status', 'manutencoes', ['status'])
    if 'ix_manutencoes_categoria' not in mnt_idxs:
        op.create_index('ix_manutencoes_categoria', 'manutencoes', ['categoria'])


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_manutencoes_categoria     ON manutencoes")
    op.execute("DROP INDEX IF EXISTS ix_manutencoes_status        ON manutencoes")
    op.execute("DROP INDEX IF EXISTS ix_turno_status              ON turnos_entrega")
    op.execute("DROP INDEX IF EXISTS ix_entregas_data_finalizacao ON entregas")
    op.execute("DROP INDEX IF EXISTS ix_entregas_filial_id        ON entregas")
    op.execute("DROP INDEX IF EXISTS ix_entregas_entregador_id    ON entregas")
    op.execute("DROP INDEX IF EXISTS ix_entregas_status           ON entregas")

    mnt_cols = _cols('manutencoes')
    for col in ('observacao_gestor', 'descricao_problema', 'motorista_id', 'status'):
        if col in mnt_cols:
            op.drop_column('manutencoes', col)
