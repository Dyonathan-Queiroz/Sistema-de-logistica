"""fase1: senha 255 e padroniza status em_rota

Revision ID: c3e8f1d20a47
Revises: 89192df1a2c4
Create Date: 2026-05-01 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "c3e8f1d20a47"
down_revision: Union[str, Sequence[str], None] = "89192df1a2c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Aumenta campo senha para suportar hash bcrypt (60 chars, mas 255 é padrão seguro)
    op.alter_column(
        "usuarios",
        "senha",
        existing_type=sa.String(100),
        type_=sa.String(255),
        existing_nullable=True,
    )

    # Padroniza status antigos para o novo valor canônico 'em_rota'
    op.execute(
        "UPDATE entregas SET status = 'em_rota' "
        "WHERE status IN ('aceito', 'em rota', 'rota')"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE entregas SET status = 'aceito' WHERE status = 'em_rota'"
    )
    op.alter_column(
        "usuarios",
        "senha",
        existing_type=sa.String(255),
        type_=sa.String(100),
        existing_nullable=True,
    )
