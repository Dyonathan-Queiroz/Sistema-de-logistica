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

Correção aplicada (2026-08-01): as colunas status, motorista_id, descricao_problema e
observacao_gestor de `manutencoes` não foram criadas por nenhuma migration anterior.
Adicionadas aqui, antes dos índices, para que ix_manutencoes_status exista sobre uma
coluna válida. Usa ADD COLUMN IF NOT EXISTS para ser idempotente em bancos que já
possuam as colunas. Os CREATE/DROP INDEX também usam IF NOT EXISTS / IF EXISTS para
o mesmo motivo.
"""
from alembic import op

revision = '3c4d5e6f7a8b'
down_revision = '2b3c4d5e6f7a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Passo 1: adiciona colunas faltando em manutencoes ANTES de criar ix_manutencoes_status.
    # IF NOT EXISTS garante idempotência em bancos que já as possuam (MySQL 8.0+).
    op.execute("""
        ALTER TABLE manutencoes
            ADD COLUMN IF NOT EXISTS `status`
                ENUM('pendente','aprovada','rejeitada') NOT NULL DEFAULT 'aprovada',
            ADD COLUMN IF NOT EXISTS `motorista_id`
                INTEGER NULL,
            ADD COLUMN IF NOT EXISTS `descricao_problema`
                VARCHAR(500) NULL,
            ADD COLUMN IF NOT EXISTS `observacao_gestor`
                VARCHAR(500) NULL
    """)

    # Passo 2: índices de performance — CREATE INDEX IF NOT EXISTS para idempotência.
    op.execute("CREATE INDEX IF NOT EXISTS ix_entregas_status           ON entregas       (`status`)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_entregas_entregador_id    ON entregas       (entregador_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_entregas_filial_id        ON entregas       (filial_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_entregas_data_finalizacao ON entregas       (data_finalizacao)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_turno_status              ON turnos_entrega (`status`)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_manutencoes_status        ON manutencoes    (`status`)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_manutencoes_categoria     ON manutencoes    (categoria)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_manutencoes_categoria     ON manutencoes")
    op.execute("DROP INDEX IF EXISTS ix_manutencoes_status        ON manutencoes")
    op.execute("DROP INDEX IF EXISTS ix_turno_status              ON turnos_entrega")
    op.execute("DROP INDEX IF EXISTS ix_entregas_data_finalizacao ON entregas")
    op.execute("DROP INDEX IF EXISTS ix_entregas_filial_id        ON entregas")
    op.execute("DROP INDEX IF EXISTS ix_entregas_entregador_id    ON entregas")
    op.execute("DROP INDEX IF EXISTS ix_entregas_status           ON entregas")
    op.execute("ALTER TABLE manutencoes DROP COLUMN IF EXISTS `observacao_gestor`")
    op.execute("ALTER TABLE manutencoes DROP COLUMN IF EXISTS `descricao_problema`")
    op.execute("ALTER TABLE manutencoes DROP COLUMN IF EXISTS `motorista_id`")
    op.execute("ALTER TABLE manutencoes DROP COLUMN IF EXISTS `status`")
