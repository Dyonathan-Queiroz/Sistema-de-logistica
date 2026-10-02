# Deploy do Sistema Logístico — roda dentro da pasta do projeto.
# git pull -> build -> recria o container -> confere se subiu e respondeu certo.
# Cada etapa só continua se a anterior deu certo; no fim mostra um resumo claro.

$ErrorActionPreference = "Continue"
$falhou = $false

function Titulo($texto) {
    Write-Host ""
    Write-Host "== $texto ==" -ForegroundColor Cyan
}

function Ok($texto) {
    Write-Host "OK - $texto" -ForegroundColor Green
}

function Falha($texto) {
    Write-Host "FALHOU - $texto" -ForegroundColor Red
}

# ---------- 1) git pull ----------
Titulo "Atualizando o codigo (git pull)"
$commitAntes = git rev-parse --short HEAD
git pull
if ($LASTEXITCODE -ne 0) {
    Falha "git pull deu erro - resolva conflito/rede antes de continuar."
    $falhou = $true
} else {
    $commitDepois = git rev-parse --short HEAD
    if ($commitAntes -eq $commitDepois) {
        Ok "ja estava atualizado (commit $commitDepois - nenhuma mudanca nova)."
    } else {
        Ok "atualizado de $commitAntes para $commitDepois."
    }
}

# ---------- 2) build ----------
if (-not $falhou) {
    Titulo "Reconstruindo a imagem (docker compose build)"
    docker compose build app
    if ($LASTEXITCODE -ne 0) {
        Falha "build da imagem deu erro - veja a mensagem acima."
        $falhou = $true
    } else {
        Ok "imagem construida."
    }
}

# ---------- 3) recriar o container ----------
if (-not $falhou) {
    Titulo "Recriando o container (docker compose up -d --force-recreate)"
    docker compose up -d --force-recreate app
    if ($LASTEXITCODE -ne 0) {
        Falha "nao conseguiu subir o container - veja a mensagem acima."
        $falhou = $true
    } else {
        Ok "comando de subida executado."
    }
}

# ---------- 4) conferir se o container esta rodando ----------
if (-not $falhou) {
    Titulo "Conferindo se o container esta de pe"
    Start-Sleep -Seconds 3
    $status = docker inspect -f "{{.State.Status}}" sistema_logistico_app 2>$null
    if ($status -eq "running") {
        Ok "container em execucao (status: $status)."
    } else {
        Falha "container nao esta rodando (status: $status) - confira 'docker compose logs app'."
        $falhou = $true
    }
}

# ---------- 5) esperar o app terminar de subir (mostrando o log na tela) ----------
if (-not $falhou) {
    Titulo "Log recente da aplicacao"
    Start-Sleep -Seconds 3
    docker compose logs --tail=40 app
    Write-Host ""
    $subiu = $false
    for ($tentativa = 1; $tentativa -le 15; $tentativa++) {
        $logRecente = docker compose logs --tail=20 app 2>$null
        if ($logRecente -match "Application startup complete") {
            $subiu = $true
            break
        }
        Start-Sleep -Seconds 2
    }
    if ($subiu) {
        Ok "aplicacao terminou de subir (achou 'Application startup complete' no log acima)."
    } else {
        Falha "nao apareceu 'Application startup complete' no log depois de ~30s - confira 'docker compose logs app'."
        $falhou = $true
    }
}

# ---------- 6) testar se o site responde de verdade ----------
if (-not $falhou) {
    Titulo "Testando se o site responde (http://localhost:8090/logistica/login)"
    try {
        $resposta = Invoke-WebRequest -Uri "http://localhost:8090/logistica/login" -UseBasicParsing -TimeoutSec 10
        if ($resposta.StatusCode -eq 200) {
            Ok "site respondeu 200 OK."
        } else {
            Falha "site respondeu com status $($resposta.StatusCode) (esperado 200)."
            $falhou = $true
        }
    } catch {
        Falha "nao conseguiu conectar em http://localhost:8090/logistica/login - $($_.Exception.Message)"
        $falhou = $true
    }
}

# ---------- resumo final ----------
Write-Host ""
if ($falhou) {
    Write-Host "===================================" -ForegroundColor Red
    Write-Host " DEPLOY COM PROBLEMA - veja acima " -ForegroundColor Red
    Write-Host "===================================" -ForegroundColor Red
    $codigoSaida = 1
} else {
    Write-Host "===================================" -ForegroundColor Green
    Write-Host " DEPLOY OK - tudo certinho!        " -ForegroundColor Green
    Write-Host " Atualizado, no ar e respondendo.  " -ForegroundColor Green
    Write-Host "===================================" -ForegroundColor Green
    $codigoSaida = 0
}

# mantém a janela aberta pra dar tempo de ler o log e o resumo acima —
# sem isso, quando o script é aberto com duplo clique, a janela fecha sozinha
# assim que termina e some tudo antes de dar tempo de ler.
Write-Host ""
try {
    Read-Host "Pressione Enter para fechar"
} catch {
    # rodando de um jeito que nao tem terminal esperando entrada (ex.: agendador de
    # tarefas) - nao ha janela pra manter aberta, so segue pro exit normalmente
}
exit $codigoSaida
