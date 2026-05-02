from pydantic import BaseModel
from typing import Optional
from datetime import datetime

# --- Esquemas para Cliente ---
class ClienteBase(BaseModel):
    nome: str
    documento: str
    telefone: str
    rua: str
    numero: str
    bairro: str
    ponto_referencia: Optional[str] = None

class ClienteCreate(ClienteBase):
    pass

class Cliente(ClienteBase):
    id: int
    class Config:
        from_attributes = True

# --- Esquemas para Entrega ---
class EntregaBase(BaseModel):
    cupom_fiscal: str
    cliente_id: int
    rua: str
    numero: str
    bairro: str
    observacao: Optional[str] = None

class EntregaCreate(EntregaBase):
    pass

class Entrega(EntregaBase):
    id: int
    status: str
    data_criacao: datetime
    entregador_id: Optional[int] = None
    data_aceite: Optional[datetime] = None
    data_finalizacao: Optional[datetime] = None

    class Config:
        from_attributes = True

# --- Esquemas para Usuário (Gestor/Entregador) ---
class UsuarioBase(BaseModel):
    username: str
    perfil: str # 'gestor', 'operador', 'entregador'
    filial_id: int

class Usuario(UsuarioBase):
    id: int
    class Config:
        from_attributes = True