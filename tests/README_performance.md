# Teste de Performance — Sistema Logístico

## Instalação

```bash
pip install locust
```

## Como rodar

### 1. Interface web (recomendado para primeira vez)

```bash
locust -f tests/locustfile.py --host https://SEU-DOMINIO.up.railway.app
```

Abra http://localhost:8089 no navegador, configure:
- **Number of users**: 20 (começa pequeno)
- **Spawn rate**: 2 (2 usuários por segundo)
- Clique em **Start swarming**

### 2. Headless (terminal, gera relatório HTML)

```bash
locust -f tests/locustfile.py \
  --host https://SEU-DOMINIO.up.railway.app \
  --headless \
  -u 20 -r 2 -t 2m \
  --html tests/relatorio.html
```

Abre `tests/relatorio.html` no browser para ver os gráficos.

## Configurar usuários de teste

Edite o topo do `locustfile.py` ou use variáveis de ambiente:

```bash
set GESTOR_USER=admin
set GESTOR_PASS=minhasenha
set OPERADOR_USER=operador1
set OPERADOR_PASS=senha123
set ENTREGADOR_USER=joao
set ENTREGADOR_PASS=senha456
```

## O que o teste simula

| Perfil | Peso | Páginas testadas |
|--------|------|-----------------|
| Gestor | 40% | Dashboard, log, ao vivo, frota, ranking, desempenho |
| Operador | 30% | Dashboard, log, busca de clientes, nova entrega |
| Entregador | 30% | Dashboard entregador, turno, checklist |

## Métricas para observar

| Métrica | Meta |
|---------|------|
| Tempo médio de resposta | < 800ms |
| 95º percentil | < 2000ms |
| Taxa de falha | < 1% |
| Requisições/segundo | sustentável por 2+ minutos |

## Escalonamento sugerido

| Fase | Usuários | Duração | Objetivo |
|------|----------|---------|----------|
| Aquecimento | 5 | 1 min | Verificar que tudo funciona |
| Normal | 20 | 2 min | Uso típico do dia a dia |
| Pico | 50 | 2 min | Simular horário de rush |
| Stress | 100 | 1 min | Encontrar limite do sistema |
