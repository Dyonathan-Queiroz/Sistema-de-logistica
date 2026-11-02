# Sistema de Logística

Sistema web de gestão logística para supermercados: despacho e acompanhamento de entregas em tempo real, controle de frota (checklists, abastecimento, manutenção, pneus) e indicadores de desempenho por motorista e filial.

Projeto de portfólio, desenvolvido em produção real para uma rede de supermercados.

## Funcionalidades

- **Entregas:** criação, aceite pelo entregador, rastreamento GPS, mapa ao vivo, estimativa de km e alertas de parada prolongada.
- **Frota:** checklist de veículos, abastecimentos, manutenção com fluxo de aprovação, controle de pneus, ranking e score de motoristas.
- **Gestão:** multi-filial, perfis (`gestor`, `operador`, `entregador`), clientes, funcionários e veículos.
- **Integração ERP:** `sync_agent/` lê pedidos do Oracle e cria clientes/entregas via API.
- **PWA:** interface mobile-first instalável no Android.

## Stack

Python 3 · FastAPI · SQLAlchemy · Alembic · MySQL · Jinja2 · Leaflet · Docker

## Segurança

Autenticação por sessão assinada (HMAC) com expiração, bloqueio de login por IP/conta, autorização por perfil validada no banco, proteção CSRF por `Origin`, cabeçalhos HTTP de segurança, SRI nos scripts de CDN e escape de dados em templates. Detalhes e como reportar falhas em [SECURITY.md](SECURITY.md).

## Como rodar

```bash
cp .env.example .env        # preencha os valores
pip install -r requirements.txt
alembic upgrade head
python seed.py              # cria filial padrão e admin (ADMIN_SENHA)
uvicorn app.main:app --reload
```

Com Docker: `docker compose up --build`.

Variáveis principais: `DATABASE_URL`, `SECRET_KEY` (obrigatória em produção), `COOKIE_SECURE=true` atrás de HTTPS, `ADMIN_SENHA`, `BACKUP_OWNER`.

## Licença

MIT — veja [LICENSE](LICENSE).
