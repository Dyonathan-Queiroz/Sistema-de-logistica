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
"""
from alembic import op

revision = '3c4d5e6f7a8b'
down_revision = '2b3c4d5e6f7a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_entregas_status",           "entregas",       ["status"])
    op.create_index("ix_entregas_entregador_id",    "entregas",       ["entregador_id"])
    op.create_index("ix_entregas_filial_id",        "entregas",       ["filial_id"])
    op.create_index("ix_entregas_data_finalizacao", "entregas",       ["data_finalizacao"])
    op.create_index("ix_turno_status",              "turnos_entrega", ["status"])
    op.create_index("ix_manutencoes_status",        "manutencoes",    ["status"])
    op.create_index("ix_manutencoes_categoria",     "manutencoes",    ["categoria"])


def downgrade() -> None:
    op.drop_index("ix_manutencoes_categoria",     table_name="manutencoes")
    op.drop_index("ix_manutencoes_status",        table_name="manutencoes")
    op.drop_index("ix_turno_status",              table_name="turnos_entrega")
    op.drop_index("ix_entregas_data_finalizacao", table_name="entregas")
    op.drop_index("ix_entregas_filial_id",        table_name="entregas")
    op.drop_index("ix_entregas_entregador_id",    table_name="entregas")
    op.drop_index("ix_entregas_status",           table_name="entregas")
