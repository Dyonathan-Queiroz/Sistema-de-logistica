from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Boolean, Text
from sqlalchemy.orm import relationship
from .database import Base
import datetime

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
    
    # --- CAMPOS DE PERFORMANCE (Performance tracking) ---
    data_criacao = Column(DateTime, default=datetime.datetime.utcnow)      # Quando o operador lançou
    data_aceite = Column(DateTime, nullable=True)                         # Quando o entregador pegou
    data_finalizacao = Column(DateTime, nullable=True)                    # Quando entregou pro cliente
    
    # Endereço (Snapshot - para não perder caso o cadastro do cliente mude)
    rua = Column(String(200))
    numero = Column(String(10))
    bairro = Column(String(100))
    observacao = Column(Text, nullable=True)
    motivo_erro = Column(Text, nullable=True)

class Veiculo(Base):
    __tablename__ = "veiculos"
    id = Column(Integer, primary_key=True, index=True)
    placa = Column(String(10), unique=True, index=True)
    modelo = Column(String(50))
    tipo = Column(String(20)) # 'Carro', 'Caminhão', 'Moto'
    # Vinculação com o entregador (Usuario)
    entregador_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)