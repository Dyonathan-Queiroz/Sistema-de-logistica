from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from .. import crud, schemas
from app.database import get_db

router = APIRouter(prefix="/clientes", tags=["clientes"])

@router.get("/{documento}", response_model=schemas.Cliente)
def read_cliente(documento: str, db: Session = Depends(get_db)):
    db_cliente = crud.get_cliente_by_documento(db, documento=documento)
    if db_cliente is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    return db_cliente

@router.post("/", response_model=schemas.Cliente)
def create_cliente(cliente: schemas.ClienteCreate, db: Session = Depends(get_db)):
    return crud.create_cliente(db=db, cliente=cliente)