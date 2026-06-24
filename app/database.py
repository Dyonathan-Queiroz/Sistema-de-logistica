from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker, declarative_base
from fastapi import HTTPException
from dotenv import load_dotenv
import os

load_dotenv()


def _build_database_url() -> str | None:
    # Tenta DATABASE_URL, MYSQL_URL e MYSQL_PRIVATE_URL (todos que Railway pode injetar)
    for key in ("DATABASE_URL", "MYSQL_URL", "MYSQL_PRIVATE_URL"):
        raw = os.getenv(key)
        if raw:
            if raw.startswith("mysql://"):
                raw = raw.replace("mysql://", "mysql+pymysql://", 1)
            return raw

    # Fallback: variáveis individuais — Railway usa dois formatos (com e sem underscore)
    host     = os.getenv("MYSQLHOST")     or os.getenv("MYSQL_HOST")
    user     = os.getenv("MYSQLUSER")     or os.getenv("MYSQL_USER")
    password = os.getenv("MYSQLPASSWORD") or os.getenv("MYSQL_PASSWORD") or ""
    port     = os.getenv("MYSQLPORT")     or os.getenv("MYSQL_PORT")     or "3306"
    database = os.getenv("MYSQLDATABASE") or os.getenv("MYSQL_DATABASE")

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
