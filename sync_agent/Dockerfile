FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY consinco_sync.py .

RUN mkdir -p /data

CMD ["python", "-u", "consinco_sync.py"]
