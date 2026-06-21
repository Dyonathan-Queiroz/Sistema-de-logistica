Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  Deploy - Sistema Logistico Gaviao" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan

Write-Host "`n[1/3] Baixando atualizacoes do GitHub..." -ForegroundColor Yellow
git pull origin main

Write-Host "`n[2/3] Reconstruindo containers..." -ForegroundColor Yellow
docker compose up -d --build

Write-Host "`n[3/3] Status dos servicos:" -ForegroundColor Yellow
docker compose ps

Write-Host "`nDeploy concluido! Acesse: http://192.168.16.250:8000" -ForegroundColor Green
