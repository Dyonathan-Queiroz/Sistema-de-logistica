from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Boolean, Text
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

class Veiculo(Base):
    __tablename__ = "veiculos"
    id = Column(Integer, primary_key=True, index=True)
    placa = Column(String(10), unique=True, index=True)
    modelo = Column(String(50))
    tipo = Column(String(20)) # 'Carro', 'Caminhão', 'Moto'
    # Vinculação com o entregador (Usuario)
    entregador_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
