from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker, declarative_base
from fastapi import HTTPException
from dotenv import load_dotenv
import os

load_dotenv()


def _build_database_url() -> str | None:
    """
    Monta a URL de conexão a partir das variáveis de ambiente.

    Prioridade:
      1. DATABASE_URL  — Railway injeta automaticamente quando o plugin MySQL está ativo
      2. Variáveis individuais (MYSQLHOST, MYSQLUSER, MYSQLPASSWORD, MYSQLPORT, MYSQLDATABASE)
         — Railway também expõe esses valores; útil quando DATABASE_URL não está disponível

    Usa sqlalchemy.engine.URL.create() para tratar senhas com caracteres especiais
    (%, @, :, etc.) sem precisar de URL-encoding manual.
    """
    raw = os.getenv("DATABASE_URL")
    if raw:
        # Railway entrega mysql:// sem driver — SQLAlchemy precisa de mysql+pymysql://
        if raw.startswith("mysql://"):
            raw = raw.replace("mysql://", "mysql+pymysql://", 1)
        return raw

    # Fallback: variáveis individuais do Railway
    host = os.getenv("MYSQLHOST")
    user = os.getenv("MYSQLUSER")
    password = os.getenv("MYSQLPASSWORD", "")
    port = os.getenv("MYSQLPORT", "3306")
    database = os.getenv("MYSQLDATABASE")

    if host and user and database:
        # URL.create() faz o encoding correto de senhas com caracteres especiais
        url_obj = URL.create(
            drivername="mysql+pymysql",
            username=user,
            password=password,
            host=host,
            port=int(port),
            database=database,
        )
        return str(url_obj)

    return None


SQLALCHEMY_DATABASE_URL = _build_database_url()

if SQLALCHEMY_DATABASE_URL:
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
else:
    engine = None
    SessionLocal = None

Base = declarative_base()


def get_db():
    if SessionLocal is None:
        raise HTTPException(
            status_code=503,
            detail="Banco de dados não configurado. Defina DATABASE_URL nas variáveis de ambiente.",
        )
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
