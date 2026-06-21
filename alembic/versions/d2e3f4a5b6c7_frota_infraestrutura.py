"""frota: checklists, turnos_entrega, abastecimentos, manutencoes, pneu_controles, motorista_scores + triggers

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-06-07

Lacunas corrigidas em relação ao spec original:
  - Checklist: adicionado motorista_id (rastreabilidade de quem inspecionou)
  - TurnoEntrega: adicionado status ENUM('aberto','encerrado')
  - Abastecimento: adicionado turno_id FK (para trigger de custo de combustível)
  - Manutencao: adicionado turno_id FK + odometro tornado nullable
  - PneuControle: adicionados data_instalacao e data_descarte
  - MotoristaScore: adicionado updated_at

Triggers criados:
  T1 trg_checklist_odometro          — atualiza veiculos.odometro_atual ao registrar checklist
  T2 trg_abastecimento_odometro_custo — atualiza odômetro + custo_combustivel do turno
  T3 trg_manutencao_odometro_custo    — atualiza odômetro + custo_manutencao do turno
  T4 trg_entrega_finalizada           — incrementa total_entregas (score) e total_cupons_dia (turno)
"""
from alembic import op
import sqlalchemy as sa

revision = 'd2e3f4a5b6c7'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None

# Nomes dos triggers — centralizados para facilitar drop no downgrade
_TRIGGERS = [
    "trg_checklist_odometro",
    "trg_abastecimento_odometro_custo",
    "trg_manutencao_odometro_custo",
    "trg_entrega_finalizada",
]


def upgrade() -> None:

    # ── 1. checklists ────────────────────────────────────────────────────────
    # Depende de: veiculos, usuarios
    op.create_table(
        "checklists",
        sa.Column("id",                  sa.Integer(),                    nullable=False, autoincrement=True),
        sa.Column("veiculo_id",          sa.Integer(),                    nullable=False),
        sa.Column("motorista_id",        sa.Integer(),                    nullable=False),  # lacuna corrigida
        sa.Column("tipo",                sa.Enum("inicio", "fim"),        nullable=False),
        sa.Column("data_hora",           sa.DateTime(),                   nullable=False),
        sa.Column("aprovado",            sa.Boolean(),                    nullable=False, server_default=sa.text("1")),
        sa.Column("itens_reprovados",    sa.JSON(),                       nullable=True),
        sa.Column("odometro_registrado", sa.Integer(),                    nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["veiculo_id"],   ["veiculos.id"],  name="fk_checklist_veiculo"),
        sa.ForeignKeyConstraint(["motorista_id"], ["usuarios.id"],  name="fk_checklist_motorista"),
    )
    op.create_index("ix_checklists_id",           "checklists", ["id"])
    op.create_index("ix_checklists_veiculo_id",   "checklists", ["veiculo_id"])
    op.create_index("ix_checklists_motorista_id", "checklists", ["motorista_id"])

    # ── 2. turnos_entrega ────────────────────────────────────────────────────
    # Depende de: veiculos, usuarios, checklists
    op.create_table(
        "turnos_entrega",
        sa.Column("id",                      sa.Integer(),                        nullable=False, autoincrement=True),
        sa.Column("veiculo_id",              sa.Integer(),                        nullable=False),
        sa.Column("motorista_id",            sa.Integer(),                        nullable=False),
        sa.Column("checklist_inicio_id",     sa.Integer(),                        nullable=False),
        sa.Column("checklist_fim_id",        sa.Integer(),                        nullable=True),
        sa.Column("status",                  sa.Enum("aberto", "encerrado"),      nullable=False, server_default="aberto"),  # lacuna corrigida
        sa.Column("data",                    sa.Date(),                           nullable=False),
        sa.Column("total_cupons_dia",        sa.Integer(),                        nullable=False, server_default=sa.text("0")),
        sa.Column("custo_combustivel_total", sa.Numeric(10, 2),                   nullable=True),
        sa.Column("custo_manutencao_total",  sa.Numeric(10, 2),                   nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["veiculo_id"],          ["veiculos.id"],   name="fk_turno_veiculo"),
        sa.ForeignKeyConstraint(["motorista_id"],        ["usuarios.id"],   name="fk_turno_motorista"),
        sa.ForeignKeyConstraint(["checklist_inicio_id"], ["checklists.id"], name="fk_turno_checklist_inicio"),
        sa.ForeignKeyConstraint(["checklist_fim_id"],    ["checklists.id"], name="fk_turno_checklist_fim"),
    )
    op.create_index("ix_turnos_entrega_id",             "turnos_entrega", ["id"])
    op.create_index("ix_turnos_entrega_veiculo_id",     "turnos_entrega", ["veiculo_id"])
    # Índice composto para lookup de turno ativo: WHERE motorista_id=? AND data=? AND status='aberto'
    op.create_index("ix_turno_motorista_data",          "turnos_entrega", ["motorista_id", "data"])

    # ── 3. abastecimentos ────────────────────────────────────────────────────
    # Depende de: veiculos, usuarios, turnos_entrega
    op.create_table(
        "abastecimentos",
        sa.Column("id",          sa.Integer(),      nullable=False, autoincrement=True),
        sa.Column("veiculo_id",  sa.Integer(),      nullable=False),
        sa.Column("motorista_id",sa.Integer(),      nullable=False),
        sa.Column("turno_id",    sa.Integer(),      nullable=True),   # lacuna corrigida
        sa.Column("data",        sa.DateTime(),     nullable=False),
        sa.Column("odometro",    sa.Integer(),      nullable=False),
        sa.Column("litros",      sa.Numeric(6, 2),  nullable=False),
        sa.Column("valor_total", sa.Numeric(10, 2), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["veiculo_id"],   ["veiculos.id"],      name="fk_abastecimento_veiculo"),
        sa.ForeignKeyConstraint(["motorista_id"], ["usuarios.id"],      name="fk_abastecimento_motorista"),
        sa.ForeignKeyConstraint(["turno_id"],     ["turnos_entrega.id"],name="fk_abastecimento_turno"),
    )
    op.create_index("ix_abastecimentos_id",          "abastecimentos", ["id"])
    op.create_index("ix_abastecimentos_veiculo_id",  "abastecimentos", ["veiculo_id"])
    op.create_index("ix_abastecimentos_turno_id",    "abastecimentos", ["turno_id"])

    # ── 4. manutencoes ───────────────────────────────────────────────────────
    # Depende de: veiculos, turnos_entrega
    op.create_table(
        "manutencoes",
        sa.Column("id",             sa.Integer(),                      nullable=False, autoincrement=True),
        sa.Column("veiculo_id",     sa.Integer(),                      nullable=False),
        sa.Column("turno_id",       sa.Integer(),                      nullable=True),   # lacuna corrigida
        sa.Column("data",           sa.Date(),                         nullable=False),
        sa.Column("odometro",       sa.Integer(),                      nullable=True),   # lacuna corrigida: nullable
        sa.Column("categoria",      sa.Enum("preventiva", "corretiva"),nullable=False),
        sa.Column("itens_trocados", sa.JSON(),                         nullable=True),
        sa.Column("valor_pecas",    sa.Numeric(10, 2),                 nullable=True),
        sa.Column("valor_mao_obra", sa.Numeric(10, 2),                 nullable=True),
        sa.Column("oficina",        sa.String(100),                    nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["veiculo_id"], ["veiculos.id"],       name="fk_manutencao_veiculo"),
        sa.ForeignKeyConstraint(["turno_id"],   ["turnos_entrega.id"], name="fk_manutencao_turno"),
    )
    op.create_index("ix_manutencoes_id",         "manutencoes", ["id"])
    op.create_index("ix_manutencoes_veiculo_id", "manutencoes", ["veiculo_id"])
    op.create_index("ix_manutencoes_turno_id",   "manutencoes", ["turno_id"])

    # ── 5. pneu_controles ────────────────────────────────────────────────────
    # Depende de: veiculos
    op.create_table(
        "pneu_controles",
        sa.Column("id",              sa.Integer(),                    nullable=False, autoincrement=True),
        sa.Column("veiculo_id",      sa.Integer(),                    nullable=False),
        sa.Column("posicao",         sa.String(20),                   nullable=False),
        sa.Column("marca",           sa.String(50),                   nullable=True),
        sa.Column("data_instalacao", sa.Date(),                       nullable=False),  # lacuna corrigida
        sa.Column("km_instalacao",   sa.Integer(),                    nullable=False),
        sa.Column("km_descarte",     sa.Integer(),                    nullable=True),
        sa.Column("data_descarte",   sa.Date(),                       nullable=True),   # lacuna corrigida
        sa.Column("status",          sa.Enum("ativo", "descartado"),  nullable=False, server_default="ativo"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["veiculo_id"], ["veiculos.id"], name="fk_pneu_veiculo"),
    )
    op.create_index("ix_pneu_controles_id",         "pneu_controles", ["id"])
    op.create_index("ix_pneu_controles_veiculo_id", "pneu_controles", ["veiculo_id"])

    # ── 6. motorista_scores ──────────────────────────────────────────────────
    # Depende de: usuarios
    op.create_table(
        "motorista_scores",
        sa.Column("id",             sa.Integer(),  nullable=False, autoincrement=True),
        sa.Column("motorista_id",   sa.Integer(),  nullable=False),
        sa.Column("score_atual",    sa.Integer(),  nullable=False, server_default=sa.text("100")),
        sa.Column("total_entregas", sa.Integer(),  nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at",     sa.DateTime(), nullable=True),  # lacuna corrigida
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("motorista_id", name="uq_motorista_scores_motorista"),
        sa.ForeignKeyConstraint(["motorista_id"], ["usuarios.id"], name="fk_score_motorista"),
    )
    op.create_index("ix_motorista_scores_id", "motorista_scores", ["id"])

    # ── TRIGGERS MYSQL ───────────────────────────────────────────────────────
    #
    # Nota: os triggers são enviados como DDL único ao MySQL via PyMySQL.
    # Não utilizar DELIMITER (é comando do cliente CLI, não SQL puro).
    # O BEGIN...END é parte da sintaxe de CREATE TRIGGER e é interpretado
    # pelo servidor MySQL diretamente, sem necessidade de delimitador especial.

    # T1 — Atualiza veiculos.odometro_atual ao registrar um checklist.
    # Regra: só atualiza se o novo KM for maior que o atual (evita regressão).
    op.execute(sa.text("""
CREATE TRIGGER trg_checklist_odometro
AFTER INSERT ON checklists
FOR EACH ROW
BEGIN
  UPDATE veiculos
  SET    odometro_atual = NEW.odometro_registrado
  WHERE  id = NEW.veiculo_id
    AND  (odometro_atual IS NULL OR NEW.odometro_registrado > odometro_atual);
END
"""))

    # T2 — Ao registrar abastecimento:
    #   a) Atualiza veiculos.odometro_atual (se KM maior)
    #   b) Acumula valor no custo_combustivel_total do turno (se turno_id informado)
    op.execute(sa.text("""
CREATE TRIGGER trg_abastecimento_odometro_custo
AFTER INSERT ON abastecimentos
FOR EACH ROW
BEGIN
  UPDATE veiculos
  SET    odometro_atual = NEW.odometro
  WHERE  id = NEW.veiculo_id
    AND  (odometro_atual IS NULL OR NEW.odometro > odometro_atual);

  IF NEW.turno_id IS NOT NULL THEN
    UPDATE turnos_entrega
    SET    custo_combustivel_total = COALESCE(custo_combustivel_total, 0) + NEW.valor_total
    WHERE  id = NEW.turno_id;
  END IF;
END
"""))

    # T3 — Ao registrar manutenção:
    #   a) Atualiza veiculos.odometro_atual (se KM informado e maior)
    #   b) Acumula (valor_pecas + valor_mao_obra) no custo_manutencao_total do turno
    op.execute(sa.text("""
CREATE TRIGGER trg_manutencao_odometro_custo
AFTER INSERT ON manutencoes
FOR EACH ROW
BEGIN
  IF NEW.odometro IS NOT NULL THEN
    UPDATE veiculos
    SET    odometro_atual = NEW.odometro
    WHERE  id = NEW.veiculo_id
      AND  (odometro_atual IS NULL OR NEW.odometro > odometro_atual);
  END IF;

  IF NEW.turno_id IS NOT NULL THEN
    UPDATE turnos_entrega
    SET    custo_manutencao_total =
             COALESCE(custo_manutencao_total, 0)
             + COALESCE(NEW.valor_pecas,    0)
             + COALESCE(NEW.valor_mao_obra, 0)
    WHERE  id = NEW.turno_id;
  END IF;
END
"""))

    # T4 — Ao finalizar uma entrega (status muda para 'finalizado'):
    #   a) Faz UPSERT em motorista_scores incrementando total_entregas
    #   b) Incrementa total_cupons_dia no turno aberto do motorista no dia
    #
    # Proteções:
    #   - Só dispara quando status muda de não-finalizado para finalizado
    #   - Requer entregador_id e data_finalizacao não nulos
    #   - Na atualização do turno: filtra status='aberto' e ORDER BY id DESC LIMIT 1
    #     (garante pegar o turno mais recente caso exista mais de um registro — edge case)
    op.execute(sa.text("""
CREATE TRIGGER trg_entrega_finalizada
AFTER UPDATE ON entregas
FOR EACH ROW
BEGIN
  IF OLD.status != 'finalizado'
     AND NEW.status = 'finalizado'
     AND NEW.entregador_id IS NOT NULL
     AND NEW.data_finalizacao IS NOT NULL
  THEN
    INSERT INTO motorista_scores (motorista_id, score_atual, total_entregas, updated_at)
      VALUES (NEW.entregador_id, 100, 1, NOW())
    ON DUPLICATE KEY UPDATE
      total_entregas = total_entregas + 1,
      updated_at     = NOW();

    UPDATE turnos_entrega
    SET    total_cupons_dia = total_cupons_dia + 1
    WHERE  motorista_id = NEW.entregador_id
      AND  data         = DATE(NEW.data_finalizacao)
      AND  status       = 'aberto'
    ORDER BY id DESC
    LIMIT 1;
  END IF;
END
"""))


def downgrade() -> None:
    # Triggers primeiro — antes de dropar as tabelas que eles referenciam
    for trigger in _TRIGGERS:
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger}"))

    # Tabelas em ordem inversa de dependência de FK
    op.drop_table("motorista_scores")
    op.drop_table("pneu_controles")
    op.drop_table("manutencoes")
    op.drop_table("abastecimentos")
    op.drop_table("turnos_entrega")
    op.drop_table("checklists")
