# Sistema de Logística

Sistema web de gestão logística para supermercados: despacho e acompanhamento de entregas em tempo real, controle de frota e indicadores de desempenho por motorista e filial.

Projeto de portfólio, desenvolvido e usado em produção real para uma rede de supermercados. Autor: **Dyonathan Henrique Queiroz Gato**.

## Resumo para quem está avaliando

| | |
|---|---|
| **Problema** | Entregas e frota de uma rede de supermercados eram controladas à mão, sem rastreio, sem histórico de manutenção e sem indicadores por motorista. |
| **Solução** | Aplicação web (PWA) com três perfis: o gestor despacha e acompanha, o operador cria entregas, o entregador executa pelo celular. |
| **Minha parte** | Projeto, back-end, front-end, banco, integração com o ERP, segurança, deploy e suporte aos usuários. |
| **Escala do código** | ~4,6 mil linhas de Python no back-end, ~90 rotas HTTP, 15 tabelas, 17 migrações Alembic e 34 templates Jinja2. |

### O que demonstra

- **Back-end com API e páginas no mesmo app:** FastAPI, SQLAlchemy e Jinja2, com schema versionado por migrações Alembic.
- **Regras de negócio reais:** fluxo de aceite e rota da entrega, fluxo de aprovação de manutenção, pontuação de motoristas e checklist de veículo por turno.
- **Banco de dados além do CRUD:** índices de desempenho e *triggers* MySQL que mantêm o custo acumulado de manutenção por veículo (ver `alembic/versions/`).
- **Dados geográficos:** rastreamento GPS, cálculo de distância percorrida (Haversine), roteirização e mapa ao vivo com Leaflet.
- **Integração com sistema legado:** um agente separado (`sync_agent/`) lê pedidos do ERP (Oracle/Consinco) e cria clientes e entregas via API.
- **Segurança tratada como requisito:** detalhes abaixo.
- **Operação:** Docker Compose, backup automático trimestral agendado com APScheduler, execução atrás de proxy reverso com prefixo de URL e teste de carga com Locust.

## Funcionalidades

- **Entregas:** criação, aceite pelo entregador, rastreamento GPS, mapa ao vivo, estimativa de km e alerta de parada prolongada.
- **Frota:** checklist de veículos, abastecimentos, manutenção com fluxo de aprovação, controle de pneus, catálogo de oficinas e peças, ranking e score de motoristas.
- **Gestão:** multi-filial com dados isolados por loja, perfis (`gestor`, `operador`, `entregador`), clientes, funcionários e veículos.
- **Desempenho:** ranking de motoristas, histórico por entregador e indicadores por filial.
- **PWA:** interface mobile-first instalável no Android, pensada para leitura rápida sob luz solar.

## Stack

Python 3 · FastAPI · SQLAlchemy · Alembic · MySQL 8 · Jinja2 · Leaflet · APScheduler · Docker

## Segurança

- Autenticação por sessão assinada (HMAC) com expiração.
- Senhas com bcrypt.
- Bloqueio de tentativas de login por IP e por conta.
- Autorização por perfil validada no banco, inclusive nas rotas de gestão.
- Proteção CSRF por verificação de `Origin`.
- Cabeçalhos HTTP de segurança, com CSP.
- SRI nos scripts de CDN.
- Escape de dados nos templates contra XSS.
- Nenhum segredo no repositório: tudo vem de variáveis de ambiente, e o `seed.py` só cria o admin se a senha for informada.

Detalhes e como reportar falhas em [SECURITY.md](SECURITY.md).

## Como rodar

```bash
cp .env.example .env        # preencha os valores
pip install -r requirements.txt
alembic upgrade head
python seed.py              # cria filial padrão e admin (ADMIN_SENHA)
uvicorn app.main:app --reload
```

Com Docker: `docker compose up --build`.

Variáveis principais: `DATABASE_URL`, `SECRET_KEY` (obrigatória em produção), `COOKIE_SECURE=true` atrás de HTTPS, `ADMIN_SENHA`, `BACKUP_OWNER`. A lista completa está em `.env.example`.

## Estrutura

```
app/            aplicação FastAPI (rotas, modelos, schemas, templates, estáticos)
alembic/        migrações do banco
sync_agent/     agente de integração com o ERP (Oracle/Consinco)
tests/          testes de carga (Locust)
seed.py         dados iniciais (filial padrão e usuários)
```

## Limitações conhecidas

- Grande parte da lógica está em um único `app/main.py`; dividir em *routers* por domínio é o próximo passo de refatoração.
- Não há suíte de testes automatizados de unidade ou integração; hoje há só teste de carga.

## Contato

Dyonathan Henrique Queiroz Gato — [GitHub](https://github.com/Dyonathan-Queiroz)

## Licença

MIT — veja [LICENSE](LICENSE).
