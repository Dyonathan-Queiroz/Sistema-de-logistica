FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY consinco_sync.py .

RUN mkdir -p /data

# SQLite de rastreamento e logs ficam em /data (volume persistente)
ENV SYNC_DATA_DIR=/data

CMD ["python", "-u", "consinco_sync.py"]
