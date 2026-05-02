from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from .. import crud, schemas
from app.database import get_db

router = APIRouter(prefix="/entregas", tags=["entregas"])

@router.post("/", response_model=schemas.Entrega)
def create_entrega(entrega: schemas.EntregaCreate, db: Session = Depends(get_db)):
    # Nota: No futuro, o operador_id virá do token JWT do usuário logado
    return crud.create_entrega(db=db, entrega=entrega, operador_id=1) 

@router.get("/disponiveis/{filial_id}", response_model=list[schemas.Entrega])
def read_entregas_disponiveis(filial_id: int, db: Session = Depends(get_db)):
    return crud.get_entregas_disponiveis(db=db, filial_id=filial_id)

@router.patch("/{entrega_id}/aceitar/{entregador_id}", response_model=schemas.Entrega)
def aceitar_entrega(entrega_id: int, entregador_id: int, db: Session = Depends(get_db)):
    return crud.aceitar_entrega(db=db, entrega_id=entrega_id, entregador_id=entregador_id)