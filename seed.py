"""
Script de inicialização — execute UMA VEZ após 'alembic upgrade head'.

    python seed.py

Cria:
  - Filial padrão "Filial Principal"
  - Usuário admin (gestor) com senha configurável via variável ADMIN_SENHA
    (padrão: admin123 — troque imediatamente em produção)
"""

import os
from dotenv import load_dotenv
from passlib.context import CryptContext
from sqlalchemy.orm import Session

load_dotenv()

from app.database import SessionLocal, engine
from app.models import Base, Filial, Usuario

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_SENHA = os.getenv("ADMIN_SENHA", "admin123")


def seed():
    Base.metadata.create_all(bind=engine)
    db: Session = SessionLocal()

    try:
        # --- Filial padrão ---
        filial = db.query(Filial).filter(Filial.nome == "Filial Principal").first()
        if not filial:
            filial = Filial(nome="Filial Principal", cidade="Cidade")
            db.add(filial)
            db.flush()
            print(f"[seed] Filial criada: id={filial.id}")
        else:
            print(f"[seed] Filial já existe: id={filial.id}")

        # --- Usuário admin ---
        admin = db.query(Usuario).filter(Usuario.username == ADMIN_USERNAME).first()
        if not admin:
            admin = Usuario(
                username=ADMIN_USERNAME,
                perfil="gestor",
                filial_id=filial.id,
                senha=pwd_context.hash(ADMIN_SENHA),
            )
            db.add(admin)
            print(f"[seed] Usuário criado: username='{ADMIN_USERNAME}' / senha='{ADMIN_SENHA}'")
        else:
            print(f"[seed] Usuário '{ADMIN_USERNAME}' já existe — nada alterado.")

        db.commit()
        print("[seed] Concluído com sucesso.")

    except Exception as e:
        db.rollback()
        print(f"[seed] ERRO: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
