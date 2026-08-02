"""add missing frota tables: oficinas, pecas_catalogo, backup_logs

Revision ID: 9a8b7c6d5e4f
Revises: 3c4d5e6f7a8b
Create Date: 2026-08-01

Tabelas criadas:
  oficinas        — mecânicas/oficinas cadastradas pelo gestor
  pecas_catalogo  — catálogo de peças e serviços frequentes
  backup_logs     — histórico de backups gerados do banco de dados

Também garante as colunas de fluxo de aprovação em manutencoes e o índice
em motorista_id — idempotente via inspect() (compatível com MySQL, sem usar
a sintaxe ADD COLUMN IF NOT EXISTS que é exclusiva do MariaDB).
"""
import sqlalchemy as sa
from alembic import op

revision = '9a8b7c6d5e4f'
down_revision = '3c4d5e6f7a8b'
branch_labels = None
depends_on = None


def _cols(table: str) -> set:
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _idxs(table: str) -> set:
    return {i['name'] for i in sa.inspect(op.get_bind()).get_indexes(table)}


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

    # ── manutencoes: colunas de aprovação ─────────────────────────────────────
    # Verifica via inspect() — ADD COLUMN IF NOT EXISTS não existe no MySQL.
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

    # ── índices ───────────────────────────────────────────────────────────────
    if 'ix_manutencoes_motorista_id' not in _idxs('manutencoes'):
        op.create_index('ix_manutencoes_motorista_id', 'manutencoes', ['motorista_id'])

    if 'ix_abastecimentos_motorista_id' not in _idxs('abastecimentos'):
        op.create_index('ix_abastecimentos_motorista_id', 'abastecimentos', ['motorista_id'])


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_abastecimentos_motorista_id ON abastecimentos")
    op.execute("DROP INDEX IF EXISTS ix_manutencoes_motorista_id    ON manutencoes")
    op.execute("DROP TABLE IF EXISTS backup_logs")
    op.execute("DROP TABLE IF EXISTS pecas_catalogo")
    op.execute("DROP TABLE IF EXISTS oficinas")
