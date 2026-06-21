"""frota triggers v2: custo_acumulado_manutencao em veiculos + triggers revisados

Revision ID: e4f5a6b7c8d9
Revises: d2e3f4a5b6c7
Create Date: 2026-06-07

Problemas corrigidos em relação à especificação original:

  ERRO 1 — Conflito de triggers (ERROR 1235):
    MySQL permite apenas 1 trigger por evento+timing por tabela.
    Os 3 triggers AFTER INSERT (checklists, abastecimentos, manutencoes)
    já existiam da migration anterior. Serão derrubados e recriados
    com lógica unificada (merge) nesta migration.

  ERRO 2 — Coluna inexistente:
    Trigger #4 referenciava `veiculos.custo_acumulado_manutencao`
    que não existia. Coluna adicionada aqui antes dos triggers.

  BUG 3 — NULL trap no abastecimento:
    `NEW.odometro > (SELECT odometro_atual ...)` retorna NULL quando
    odometro_atual é NULL (veículo novo) → condicional nunca dispara.
    Corrigido com COALESCE.

  BUG 4 — NULL propagation na manutenção:
    `NEW.valor_pecas + NEW.valor_mao_obra` retorna NULL se qualquer
    campo for NULL (ambos nullable). Corrigido com COALESCE em cada operando.

Triggers após esta migration:
  trg_chk_before_valida_odometro    BEFORE INSERT checklists   — SIGNAL se KM regressivo
  trg_chk_after_atualiza_km         AFTER INSERT  checklists   — UPDATE odometro_atual (sem condição: BEFORE já validou)
  trg_abt_after_odometro_custo      AFTER INSERT  abastecimentos — UPDATE odometro (NULL-safe) + custo turno
  trg_mnt_after_odometro_custo      AFTER INSERT  manutencoes    — UPDATE odometro + custo turno + custo_acumulado veículo
  trg_entrega_finalizada            AFTER UPDATE  entregas       — inalterado (score + cupons turno)
"""
from alembic import op
import sqlalchemy as sa

revision = 'e4f5a6b7c8d9'
down_revision = 'd2e3f4a5b6c7'
branch_labels = None
depends_on = None

# ── Triggers desta migration (para facilitar o downgrade) ──────────────────
_TRIGGERS_NOVOS = [
    "trg_chk_before_valida_odometro",
    "trg_chk_after_atualiza_km",
    "trg_abt_after_odometro_custo",
    "trg_mnt_after_odometro_custo",
]
# Triggers da migration anterior que serão substituídos
_TRIGGERS_ANTIGOS = [
    "trg_checklist_odometro",
    "trg_abastecimento_odometro_custo",
    "trg_manutencao_odometro_custo",
]


def upgrade() -> None:

    # ── PASSO 1: adicionar coluna custo_acumulado_manutencao em veiculos ─────
    # Deve vir ANTES dos triggers para que o UPDATE no Trigger #4 funcione.
    op.add_column(
        "veiculos",
        sa.Column(
            "custo_acumulado_manutencao",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
    )

    # ── PASSO 2: derrubar os 3 triggers da migration anterior que conflitam ──
    # MySQL não permite dois triggers com o mesmo evento+timing na mesma tabela.
    # Ordem não importa para DROPs, mas por clareza derrubamos antes de criar.
    for t in _TRIGGERS_ANTIGOS:
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {t}"))

    # =========================================================================
    # TRIGGER 1 — BEFORE INSERT ON checklists
    # VALIDAÇÃO DE SEGURANÇA: rejeita odômetro regressivo com SIGNAL.
    #
    # Análise de NULL:
    #   Se odometro_atual IS NULL (veículo novo ou nunca registrado), a
    #   comparação `NEW.odometro_registrado < NULL` retorna NULL → IF não
    #   dispara → qualquer valor é aceito. Comportamento CORRETO.
    #
    # Por que BEFORE e não CHECK CONSTRAINT?
    #   MySQL < 8.0.16 não suporta CHECK CONSTRAINT com subconsulta.
    #   Mesmo no 8.0.16+, a restrição não pode referenciar outra tabela.
    #   O BEFORE INSERT é a única forma portável de validação cross-table.
    # =========================================================================
    op.execute(sa.text("""
CREATE TRIGGER trg_chk_before_valida_odometro
BEFORE INSERT ON checklists
FOR EACH ROW
BEGIN
  DECLARE v_odometro_atual INT;

  -- Lê o odômetro atual do veículo em uma variável local
  SELECT odometro_atual
    INTO v_odometro_atual
    FROM veiculos
   WHERE id = NEW.veiculo_id;

  -- Só valida se o veículo já tem um KM registrado (não é nulo)
  IF v_odometro_atual IS NOT NULL
     AND NEW.odometro_registrado < v_odometro_atual
  THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'Odometro menor que o atual do veiculo';
  END IF;
END
"""))

    # =========================================================================
    # TRIGGER 2 — AFTER INSERT ON checklists
    # ATUALIZAÇÃO DE KM: persiste o novo odômetro no veículo.
    #
    # Simplificação em relação ao trigger anterior:
    #   O trigger anterior tinha a condição
    #     `AND (odometro_atual IS NULL OR NEW.odometro_registrado > odometro_atual)`
    #   Agora essa verificação é DESNECESSÁRIA: o BEFORE INSERT (Trigger 1) já
    #   garante que odometro_registrado >= odometro_atual. O UPDATE pode ser
    #   incondicional — qualquer INSERT que chegue aqui é válido.
    #
    # Por que não usar WHERE para evitar UPDATE desnecessário?
    #   Um UPDATE "sem efeito" (novo valor = atual) é barato. O WHERE extra
    #   exigiria um SELECT implícito que costuma ser mais caro. Mantemos simples.
    # =========================================================================
    op.execute(sa.text("""
CREATE TRIGGER trg_chk_after_atualiza_km
AFTER INSERT ON checklists
FOR EACH ROW
BEGIN
  UPDATE veiculos
  SET    odometro_atual = NEW.odometro_registrado
  WHERE  id = NEW.veiculo_id;
END
"""))

    # =========================================================================
    # TRIGGER 3 — AFTER INSERT ON abastecimentos
    # ATUALIZAÇÃO VIA POSTO: atualiza odômetro + acumula custo no turno.
    #
    # Merge com lógica anterior (turno):
    #   O trigger anterior já cuidava de atualizar custo_combustivel_total
    #   no turno vinculado. Essa lógica é PRESERVADA aqui para não criar
    #   inconsistência nos custos consolidados do TurnoEntrega.
    #
    # Correção do NULL trap (Bug 3):
    #   Original: `IF NEW.odometro > (SELECT odometro_atual ...)`
    #   Problema: quando odometro_atual IS NULL → comparação retorna NULL
    #             → IF avalia como FALSE → primeiro abastecimento nunca
    #             atualiza o veículo.
    #   Corrigido: COALESCE(v_odometro_atual, 0) trata NULL como 0.
    # =========================================================================
    op.execute(sa.text("""
CREATE TRIGGER trg_abt_after_odometro_custo
AFTER INSERT ON abastecimentos
FOR EACH ROW
BEGIN
  DECLARE v_odometro_atual INT;

  SELECT odometro_atual
    INTO v_odometro_atual
    FROM veiculos
   WHERE id = NEW.veiculo_id;

  -- COALESCE evita NULL trap: veículo novo (odometro_atual NULL) aceita qualquer KM
  IF NEW.odometro > COALESCE(v_odometro_atual, 0) THEN
    UPDATE veiculos
    SET    odometro_atual = NEW.odometro
    WHERE  id = NEW.veiculo_id;
  END IF;

  -- Acumula custo de combustível no turno vinculado (lógica preservada)
  IF NEW.turno_id IS NOT NULL THEN
    UPDATE turnos_entrega
    SET    custo_combustivel_total = COALESCE(custo_combustivel_total, 0) + NEW.valor_total
    WHERE  id = NEW.turno_id;
  END IF;
END
"""))

    # =========================================================================
    # TRIGGER 4 — AFTER INSERT ON manutencoes
    # INTELIGÊNCIA DE CUSTO: odômetro + custo no turno + custo acumulado veículo.
    #
    # Merge com lógica anterior (turno):
    #   A lógica de custo_manutencao_total no TurnoEntrega é PRESERVADA.
    #
    # Novo bloco adicionado:
    #   Acumula o custo total (peças + mão de obra) em veiculos.custo_acumulado_manutencao.
    #   Esse campo dá ao gestor a visão do custo histórico total do veículo,
    #   independentemente de qual turno gerou a manutenção.
    #
    # Correção do NULL propagation (Bug 4):
    #   `NEW.valor_pecas + NEW.valor_mao_obra` = NULL se qualquer operando for NULL.
    #   Corrigido: COALESCE em cada operando antes da soma.
    #
    # Custo calculado UMA VEZ em variável local para não repetir a expressão.
    # =========================================================================
    op.execute(sa.text("""
CREATE TRIGGER trg_mnt_after_odometro_custo
AFTER INSERT ON manutencoes
FOR EACH ROW
BEGIN
  DECLARE v_custo_total DECIMAL(12, 2);

  -- Calcula custo total com proteção contra NULL em cada operando
  SET v_custo_total = COALESCE(NEW.valor_pecas, 0) + COALESCE(NEW.valor_mao_obra, 0);

  -- Atualiza odômetro do veículo (apenas se KM foi informado e é maior)
  IF NEW.odometro IS NOT NULL THEN
    UPDATE veiculos
    SET    odometro_atual = NEW.odometro
    WHERE  id = NEW.veiculo_id
      AND  (odometro_atual IS NULL OR NEW.odometro > odometro_atual);
  END IF;

  -- Acumula custo histórico de manutenção no veículo
  UPDATE veiculos
  SET    custo_acumulado_manutencao = COALESCE(custo_acumulado_manutencao, 0) + v_custo_total
  WHERE  id = NEW.veiculo_id;

  -- Acumula custo no turno vinculado (manutenção corretiva durante o turno)
  IF NEW.turno_id IS NOT NULL THEN
    UPDATE turnos_entrega
    SET    custo_manutencao_total = COALESCE(custo_manutencao_total, 0) + v_custo_total
    WHERE  id = NEW.turno_id;
  END IF;
END
"""))


def downgrade() -> None:
    # Remove triggers criados nesta migration
    for t in _TRIGGERS_NOVOS:
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {t}"))

    # Restaura os triggers originais da migration anterior
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

    # Remove a coluna adicionada
    op.drop_column("veiculos", "custo_acumulado_manutencao")
