"""add municipio e estado em clientes

Revision ID: e5f6a7b8c9d0
Revises: d1e2f3a4b5c6
Create Date: 2026-05-03 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    if not _column_exists("clientes", "municipio"):
        op.add_column("clientes", sa.Column("municipio", sa.String(length=100), nullable=True))
    if not _column_exists("clientes", "estado"):
        op.add_column("clientes", sa.Column("estado", sa.String(length=2), nullable=True))


def downgrade() -> None:
    if _column_exists("clientes", "estado"):
        op.drop_column("clientes", "estado")
    if _column_exists("clientes", "municipio"):
        op.drop_column("clientes", "municipio")
