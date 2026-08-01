"""add missing frota tables: oficinas, pecas_catalogo, backup_logs

Revision ID: 9a8b7c6d5e4f
Revises: 3c4d5e6f7a8b
Create Date: 2026-08-01

Tabelas criadas:
  oficinas        — mecânicas/oficinas cadastradas pelo gestor
  pecas_catalogo  — catálogo de peças e serviços frequentes
  backup_logs     — histórico de backups gerados do banco de dados

Essas tabelas existiam em app/models.py mas nunca foram criadas por nenhuma
migration. Em um banco limpo (ex: novo deploy no Railway), qualquer rota que
acessasse essas tabelas retornava 500 "Table doesn't exist".

Também garante, via IF NOT EXISTS, as colunas de fluxo de aprovação em
manutencoes e o índice em motorista_id — belt-and-suspenders para bancos de
produção que tenham chegado a este ponto pelo caminho alternativo.
"""
import sqlalchemy as sa
from alembic import op

revision = '9a8b7c6d5e4f'
down_revision = '3c4d5e6f7a8b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── oficinas ──────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS oficinas (
            id       INTEGER      NOT NULL AUTO_INCREMENT,
            nome     VARCHAR(100) NOT NULL,
            telefone VARCHAR(20)  NULL,
            endereco VARCHAR(200) NULL,
            ativo    TINYINT(1)   NOT NULL DEFAULT 1,
            PRIMARY KEY (id),
            KEY ix_oficinas_id (id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)

    # ── pecas_catalogo ────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS pecas_catalogo (
            id        INTEGER      NOT NULL AUTO_INCREMENT,
            nome      VARCHAR(100) NOT NULL,
            categoria VARCHAR(50)  NULL,
            unidade   VARCHAR(20)  NULL DEFAULT 'un',
            ativo     TINYINT(1)   NOT NULL DEFAULT 1,
            PRIMARY KEY (id),
            KEY ix_pecas_catalogo_id (id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)

    # ── backup_logs ───────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS backup_logs (
            id         INTEGER      NOT NULL AUTO_INCREMENT,
            tipo       VARCHAR(20)  NOT NULL DEFAULT 'manual',
            criado_em  DATETIME     NOT NULL,
            tamanho_kb INTEGER      NULL,
            status     VARCHAR(20)  NOT NULL DEFAULT 'ok',
            obs        VARCHAR(255) NULL,
            dados_gz   LONGBLOB     NULL,
            PRIMARY KEY (id),
            KEY ix_backup_logs_id (id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)

    # ── manutencoes: garante colunas e índice de motorista_id ─────────────────
    # Idempotente: se 3c4d5e6f7a8b já foi aplicada corretamente, é no-op.
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
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_manutencoes_motorista_id ON manutencoes (motorista_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_abastecimentos_motorista_id ON abastecimentos (motorista_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_abastecimentos_motorista_id ON abastecimentos")
    op.execute("DROP INDEX IF EXISTS ix_manutencoes_motorista_id    ON manutencoes")
    op.execute("DROP TABLE IF EXISTS backup_logs")
    op.execute("DROP TABLE IF EXISTS pecas_catalogo")
    op.execute("DROP TABLE IF EXISTS oficinas")
