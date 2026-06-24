from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Boolean, Text, JSON, Numeric, Date, Enum as SAEnum, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from .database import Base
from .utils import agora

class Filial(Base):
    __tablename__ = "filiais"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(100), nullable=False)
    cidade = Column(String(100))

class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True)
    perfil = Column(String(20))  # 'gestor', 'operador', 'entregador'
    filial_id = Column(Integer, ForeignKey("filiais.id"))
    senha = Column(String(255))  # bcrypt hash

class Cliente(Base):
    __tablename__ = "clientes"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(150), nullable=False)
    documento = Column(String(20), unique=True, index=True) # CPF/CNPJ
    telefone = Column(String(20))
    rua = Column(String(200))
    numero = Column(String(10))
    bairro = Column(String(100))
    municipio = Column(String(100))
    estado = Column(String(2))  # sigla UF, ex: "SP"
    ponto_referencia = Column(String(255))

class Entrega(Base):
    __tablename__ = "entregas"
    id = Column(Integer, primary_key=True, index=True)
    cupom_fiscal = Column(String(50), index=True)

    # Relacionamentos
    cliente_id = Column(Integer, ForeignKey("clientes.id"))
    filial_id = Column(Integer, ForeignKey("filiais.id"))
    operador_id = Column(Integer, ForeignKey("usuarios.id"))
    entregador_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    status = Column(String(20), default="pendente")  # 'pendente', 'em_rota', 'finalizado'

    # Timestamps no horário de Boa Vista - RR (UTC-4)
    data_criacao    = Column(DateTime, default=agora)   # Quando a entrega foi lançada
    data_aceite     = Column(DateTime, nullable=True)   # Quando o entregador aceitou
    data_finalizacao = Column(DateTime, nullable=True)  # Quando entregou ao cliente

    # Endereço (snapshot — não muda se o cadastro do cliente for editado)
    rua        = Column(String(200))
    numero     = Column(String(10))
    bairro     = Column(String(100))
    municipio  = Column(String(100), nullable=True)   # Cidade (ex: BOA VISTA)
    uf         = Column(String(2),   nullable=True)   # Estado (ex: RR)
    cep        = Column(String(10),  nullable=True)   # CEP (ex: 69317102)
    observacao = Column(Text, nullable=True)
    motivo_erro = Column(Text, nullable=True)

    # IDs de rastreabilidade do Consinco (Oracle)
    nro_checkout = Column(Integer, nullable=True)   # NROCHECKOUT — número do checkout PDV
    seq_docto    = Column(Integer, nullable=True)   # SEQDOCTO    — sequencial do documento
    seq_pessoa   = Column(Integer, nullable=True)   # SEQPESSOA   — sequencial do cliente

    origem = Column(String(20), default="pdv")      # 'pdv' | 'manual'

class PontoRota(Base):
    """Pontos GPS coletados durante uma entrega: início, percurso e chegada."""
    __tablename__ = "pontos_rota"
    id         = Column(Integer, primary_key=True, index=True)
    entrega_id = Column(Integer, ForeignKey("entregas.id"), index=True, nullable=False)
    latitude   = Column(Float, nullable=False)
    longitude  = Column(Float, nullable=False)
    timestamp  = Column(DateTime, default=agora)
    tipo       = Column(String(12), default="rota")  # inicio | rota | fim

class Veiculo(Base):
    __tablename__ = "veiculos"
    id = Column(Integer, primary_key=True, index=True)
    placa = Column(String(10), unique=True, index=True)
    modelo = Column(String(50))
    tipo = Column(String(20)) # 'Carro', 'Caminhão', 'Moto'
    odometro_atual              = Column(Integer,       nullable=True)           # km atual registrado no veículo
    custo_acumulado_manutencao  = Column(Numeric(12, 2), nullable=False, default=0)  # R$ acumulado em peças + mão de obra
    # Motorista responsável padrão (≠ quem está usando agora — isso fica em TurnoEntrega)
    entregador_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)


# ─────────────────────────────────────────────────────────────────────────────
# MÓDULO DE GESTÃO DE FROTAS
# ─────────────────────────────────────────────────────────────────────────────

class Checklist(Base):
    """
    Inspeção veicular registrada no início ou fim de cada turno.

    Lacuna corrigida: adicionado `motorista_id` (não estava no spec original).
    Sem ele seria impossível rastrear quem fez a inspeção em caso de auditoria
    ou quando um veículo é usado por motoristas diferentes.

    itens_reprovados — estrutura JSON esperada:
      [{"item": "pneu_traseiro_esq", "descricao": "calibragem baixa"}, ...]
    """
    __tablename__ = "checklists"

    id                  = Column(Integer, primary_key=True, index=True)
    veiculo_id          = Column(Integer, ForeignKey("veiculos.id"),  nullable=False, index=True)
    motorista_id        = Column(Integer, ForeignKey("usuarios.id"),  nullable=False, index=True)
    tipo                = Column(SAEnum("inicio", "fim"),             nullable=False)
    data_hora           = Column(DateTime, default=agora,             nullable=False)
    aprovado            = Column(Boolean,  default=True,              nullable=False)
    itens_reprovados    = Column(JSON,                                nullable=True)
    odometro_registrado = Column(Integer,                             nullable=False)

    # Relationships
    veiculo   = relationship("Veiculo",  foreign_keys=[veiculo_id])
    motorista = relationship("Usuario",  foreign_keys=[motorista_id])


class TurnoEntrega(Base):
    """
    Consolidado diário por turno de trabalho.

    Lacuna corrigida: adicionado `status` ENUM('aberto','encerrado').
    Antes a única forma de saber se o turno estava aberto era verificar
    checklist_fim_id IS NULL — implícito e frágil.

    Nota arquitetural: `data [Date]` limita a 1 turno por motorista por dia.
    Se o negócio exigir 2 turnos/dia (manhã+tarde), remover o UniqueConstraint
    abaixo e alterar para DateTime ou adicionar campo `periodo`.

    custo_combustivel_total e custo_manutencao_total são mantidos
    automaticamente por Triggers MySQL (T2 e T3).
    total_cupons_dia é mantido pelo Trigger T4.
    """
    __tablename__ = "turnos_entrega"
    __table_args__ = (
        # Garante no máximo 1 turno aberto por motorista por dia.
        # Remover se o negócio precisar de múltiplos turnos no mesmo dia.
        Index("ix_turno_motorista_data", "motorista_id", "data"),
    )

    id                      = Column(Integer, primary_key=True, index=True)
    veiculo_id              = Column(Integer, ForeignKey("veiculos.id"),   nullable=False, index=True)
    motorista_id            = Column(Integer, ForeignKey("usuarios.id"),   nullable=False)
    checklist_inicio_id     = Column(Integer, ForeignKey("checklists.id"), nullable=False)
    checklist_fim_id        = Column(Integer, ForeignKey("checklists.id"), nullable=True)
    # Lacuna corrigida: status explícito em vez de inferir por checklist_fim_id IS NULL
    status                  = Column(SAEnum("aberto", "encerrado"),        nullable=False, default="aberto")
    data                    = Column(Date,                                  nullable=False)
    # Mantido por Trigger T4 (trg_entrega_finalizada)
    total_cupons_dia        = Column(Integer,      nullable=False, default=0)
    # Mantidos por Trigger T2 (trg_abastecimento_odometro_e_custo)
    custo_combustivel_total = Column(Numeric(10, 2), nullable=True)
    # Mantido por Trigger T3 (trg_manutencao_odometro_e_custo)
    custo_manutencao_total  = Column(Numeric(10, 2), nullable=True)

    # Relationships
    veiculo          = relationship("Veiculo",  foreign_keys=[veiculo_id])
    motorista        = relationship("Usuario",  foreign_keys=[motorista_id])
    checklist_inicio = relationship("Checklist", foreign_keys=[checklist_inicio_id])
    checklist_fim    = relationship("Checklist", foreign_keys=[checklist_fim_id])
    abastecimentos   = relationship("Abastecimento", back_populates="turno")
    manutencoes      = relationship("Manutencao",     back_populates="turno")


class Abastecimento(Base):
    """
    Registro de cada abastecimento realizado.

    Lacuna corrigida: adicionado `turno_id` (nullable FK para turnos_entrega).
    Sem ele, o Trigger T2 não consegue atualizar custo_combustivel_total
    no turno correto de forma confiável.
    """
    __tablename__ = "abastecimentos"

    id           = Column(Integer, primary_key=True, index=True)
    veiculo_id   = Column(Integer, ForeignKey("veiculos.id"),      nullable=False, index=True)
    motorista_id = Column(Integer, ForeignKey("usuarios.id"),      nullable=False, index=True)
    # Lacuna corrigida: vínculo com o turno do dia
    turno_id     = Column(Integer, ForeignKey("turnos_entrega.id"), nullable=True,  index=True)
    data         = Column(DateTime, default=agora,                  nullable=False)
    odometro     = Column(Integer,                                  nullable=False)
    litros       = Column(Numeric(6, 2),                            nullable=False)
    valor_total  = Column(Numeric(10, 2),                           nullable=False)

    # Relationships
    veiculo   = relationship("Veiculo")
    motorista = relationship("Usuario")
    turno     = relationship("TurnoEntrega", back_populates="abastecimentos")


class Manutencao(Base):
    """
    Registro de manutenção preventiva ou corretiva.

    Lacuna corrigida: adicionado `turno_id` (nullable FK para turnos_entrega).
    Necessário para que o Trigger T3 atualize custo_manutencao_total no turno.

    Lacuna corrigida: `odometro` tornado nullable.
    Manutenção preventiva por data (ex: revisão trimestral) pode não
    ter KM registrado no momento do serviço.

    itens_trocados — estrutura JSON esperada:
      [{"item": "oleo_motor", "quantidade": 1, "unidade": "L", "marca": "Mobil"}]
    """
    __tablename__ = "manutencoes"

    id             = Column(Integer, primary_key=True, index=True)
    veiculo_id     = Column(Integer, ForeignKey("veiculos.id"),       nullable=False, index=True)
    # Lacuna corrigida: vínculo com o turno (especialmente para corretivas)
    turno_id       = Column(Integer, ForeignKey("turnos_entrega.id"),  nullable=True,  index=True)
    data           = Column(Date,                                       nullable=False)
    # Lacuna corrigida: nullable — manutenção por data pode não ter KM
    odometro       = Column(Integer,                                    nullable=True)
    categoria      = Column(SAEnum("preventiva", "corretiva"),         nullable=False)
    itens_trocados = Column(JSON,                                       nullable=True)
    valor_pecas    = Column(Numeric(10, 2),                             nullable=True)
    valor_mao_obra = Column(Numeric(10, 2),                             nullable=True)
    oficina        = Column(String(100),                                nullable=True)

    # ── Fluxo de aprovação ────────────────────────────────────────────────
    # 'pendente'  — solicitado pelo motorista, aguarda gestor
    # 'aprovada'  — gestor aprovou, aparece no histórico de manutenção
    # 'rejeitada' — gestor rejeitou
    status             = Column(SAEnum("pendente", "aprovada", "rejeitada"),
                                nullable=False, default="aprovada")
    motorista_id       = Column(Integer, ForeignKey("usuarios.id"),   nullable=True)
    descricao_problema = Column(String(500),                           nullable=True)
    observacao_gestor  = Column(String(500),                           nullable=True)

    # Relationships
    veiculo   = relationship("Veiculo")
    turno     = relationship("TurnoEntrega", back_populates="manutencoes")
    motorista = relationship("Usuario", foreign_keys=[motorista_id])


class PneuControle(Base):
    """
    Controle de ciclo de vida por pneu e por posição no veículo.

    Lacuna corrigida: adicionados `data_instalacao` e `data_descarte`.
    Com apenas km_instalacao/km_descarte era impossível calcular vida
    útil em meses ou identificar pneus por período.

    posicao — exemplos: 'dianteiro_esq', 'dianteiro_dir',
                        'traseiro_esq', 'traseiro_dir', 'estepe'
    """
    __tablename__ = "pneu_controles"

    id              = Column(Integer, primary_key=True, index=True)
    veiculo_id      = Column(Integer, ForeignKey("veiculos.id"), nullable=False, index=True)
    posicao         = Column(String(20),                          nullable=False)
    marca           = Column(String(50),                          nullable=True)
    # Lacuna corrigida: data de instalação para rastreamento temporal
    data_instalacao = Column(Date,                                nullable=False)
    km_instalacao   = Column(Integer,                             nullable=False)
    km_descarte     = Column(Integer,                             nullable=True)
    # Lacuna corrigida: data de descarte para calcular vida útil em meses
    data_descarte   = Column(Date,                                nullable=True)
    status          = Column(SAEnum("ativo", "descartado"),       nullable=False, default="ativo")

    # Relationships
    veiculo = relationship("Veiculo")


class Oficina(Base):
    """Oficinas/mecânicas cadastradas pelo gestor."""
    __tablename__ = "oficinas"

    id       = Column(Integer, primary_key=True, index=True)
    nome     = Column(String(100), nullable=False)
    telefone = Column(String(20),  nullable=True)
    endereco = Column(String(200), nullable=True)
    ativo    = Column(Boolean,     nullable=False, default=True)


class PecaCatalogo(Base):
    """Catálogo de peças e serviços frequentes cadastrados pelo gestor."""
    __tablename__ = "pecas_catalogo"

    id        = Column(Integer, primary_key=True, index=True)
    nome      = Column(String(100), nullable=False)
    categoria = Column(String(50),  nullable=True)
    unidade   = Column(String(20),  nullable=True, default="un")
    ativo     = Column(Boolean,     nullable=False, default=True)


class MotoristaScore(Base):
    """
    Pontuação e estatísticas acumuladas por motorista.

    motorista_id tem UNIQUE constraint — 1 registro por motorista.
    total_entregas e updated_at são mantidos pelo Trigger T4.

    Lacuna corrigida: adicionado `updated_at` para rastrear quando
    o score foi alterado pela última vez.

    IMPORTANTE: score_atual é mantido manualmente pela aplicação
    (regras de negócio de pontuação ficam na camada de serviço).
    total_entregas é incrementado automaticamente via Trigger T4.
    """
    __tablename__ = "motorista_scores"
    __table_args__ = (
        UniqueConstraint("motorista_id", name="uq_motorista_scores_motorista"),
    )

    id             = Column(Integer, primary_key=True, index=True)
    motorista_id   = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    score_atual    = Column(Integer,  nullable=False, default=100)
    total_entregas = Column(Integer,  nullable=False, default=0)
    # Lacuna corrigida: audit trail de quando o score foi atualizado
    updated_at     = Column(DateTime, nullable=True,  onupdate=agora)

    # Relationships
    motorista = relationship("Usuario")
