#!/bin/sh
set -e

echo "======================================"
echo "  Deploy — Sistema Logístico Gavião"
echo "======================================"

# Puxa as últimas alterações do GitHub
echo ""
echo "[1/3] Baixando atualizações..."
git pull origin main

# Reconstrói e reinicia os containers
echo ""
echo "[2/3] Reconstruindo containers..."
docker compose up -d --build

# Exibe o status final
echo ""
echo "[3/3] Status dos serviços:"
docker compose ps

echo ""
echo "✓ Deploy concluído!"
echo "  Acesse: http://$(hostname -I | awk '{print $1}'):8000"
