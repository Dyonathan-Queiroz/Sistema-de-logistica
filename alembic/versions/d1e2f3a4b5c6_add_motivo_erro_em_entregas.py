"""add motivo_erro em entregas

Revision ID: d1e2f3a4b5c6
Revises: c3e8f1d20a47
Create Date: 2026-05-03 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c3e8f1d20a47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("entregas", sa.Column("motivo_erro", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("entregas", "motivo_erro")
