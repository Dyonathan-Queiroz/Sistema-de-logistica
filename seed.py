"""
Script de inicialização — executado em cada deploy pelo Procfile.

    alembic upgrade head && python seed.py && uvicorn ...

Cria (apenas se não existirem):
  - Filial padrão "Filial Principal"
  - Usuário admin (gestor) com senha definida via variável ADMIN_SENHA

IMPORTANTE: Defina ADMIN_SENHA nas variáveis de ambiente do Railway.
Se o admin já existir no banco, o seed é pulado sem erro.
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
ADMIN_SENHA    = os.getenv("ADMIN_SENHA", "")


def seed():
    if engine is None:
        print("[seed] DATABASE_URL não definida — pulando seed.")
        return

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
            # Só cria se a senha foi definida via variável de ambiente
            if not ADMIN_SENHA:
                print(
                    f"[seed] AVISO: usuário '{ADMIN_USERNAME}' não existe e ADMIN_SENHA "
                    "não está definida — admin NÃO foi criado.\n"
                    "  Defina ADMIN_SENHA nas variáveis do Railway e faça um novo deploy."
                )
            else:
                admin = Usuario(
                    username=ADMIN_USERNAME,
                    perfil="gestor",
                    filial_id=filial.id,
                    senha=pwd_context.hash(ADMIN_SENHA),
                )
                db.add(admin)
                print(f"[seed] Usuário '{ADMIN_USERNAME}' criado com sucesso.")
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
