FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc default-libmysqlclient-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Mesmo comando do Procfile (usado no Railway) — migra o banco e cria o admin (se ainda não
# existir) antes de subir o servidor. Sem isso, um "docker compose up" num banco novo (como no
# primeiro deploy no servidor do Gavião) subiria sem tabela nenhuma criada.
CMD ["sh", "-c", "alembic upgrade head && python seed.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
