from sqlalchemy.orm import Session
from . import models, schemas

# --- CRUD de Clientes ---
def get_cliente_by_documento(db: Session, documento: str):
    return db.query(models.Cliente).filter(models.Cliente.documento == documento).first()

def create_cliente(db: Session, cliente: schemas.ClienteCreate):
    db_cliente = models.Cliente(**cliente.model_dump())
    db.add(db_cliente)
    db.commit()
    db.refresh(db_cliente)
    return db_cliente

# --- CRUD de Entregas ---
def create_entrega(db: Session, entrega: schemas.EntregaCreate, operador_id: int):
    # Cria a entrega associando ao operador que está logado no PDV
    db_entrega = models.Entrega(**entrega.model_dump(), operador_id=operador_id)
    db.add(db_entrega)
    db.commit()
    db.refresh(db_entrega)
    return db_entrega

def get_entregas_disponiveis(db: Session, filial_id: int):
    # Filtra entregas pendentes para o entregador visualizar
    return db.query(models.Entrega).filter(
        models.Entrega.status == "pendente",
        models.Entrega.filial_id == filial_id
    ).all()

def aceitar_entrega(db: Session, entrega_id: int, entregador_id: int):
    from datetime import datetime
    entrega = db.query(models.Entrega).filter(models.Entrega.id == entrega_id).first()
    if entrega and entrega.status == "pendente":
        entrega.entregador_id = entregador_id
        entrega.status = "em_rota"
        entrega.data_aceite = datetime.utcnow()
        db.commit()
        db.refresh(entrega)
    return entrega


def finalizar_entrega(db: Session, entrega_id: int, entregador_id: int):
    from datetime import datetime
    entrega = db.query(models.Entrega).filter(models.Entrega.id == entrega_id).first()
    if entrega and entrega.status == "em_rota" and entrega.entregador_id == entregador_id:
        entrega.status = "finalizado"
        entrega.data_finalizacao = datetime.utcnow()
        db.commit()
        db.refresh(entrega)
    return entrega