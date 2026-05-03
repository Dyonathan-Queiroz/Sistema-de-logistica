from logging.config import fileConfig
import os

from sqlalchemy import create_engine, pool
from alembic import context
from dotenv import load_dotenv

load_dotenv()

from app.database import Base, SQLALCHEMY_DATABASE_URL
from app.models import Entrega, Usuario, Cliente, Filial, Veiculo

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Registra a URL no config do Alembic (usado apenas no modo offline).
# No modo online criamos o engine diretamente — sem passar pelo configparser —
# para evitar InterpolationSyntaxError com senhas que contenham '%'.
if SQLALCHEMY_DATABASE_URL:
    config.set_main_option("sqlalchemy.url", SQLALCHEMY_DATABASE_URL.replace("%", "%%"))


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Cria o engine direto da URL em memória — bypassa o configparser
    # e elimina qualquer risco de interpolação de '%'.
    if not SQLALCHEMY_DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL não definida. Configure a variável de ambiente antes de rodar migrations."
        )
    connectable = create_engine(SQLALCHEMY_DATABASE_URL, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
