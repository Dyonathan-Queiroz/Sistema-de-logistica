# 🦅 Sistema Logístico — Supermercado Gavião

Plataforma de gestão logística desenvolvida para o **Supermercado Gavião** (Boa Vista/RR).  
Centraliza o controle de entregas, gestão de frota, desempenho de motoristas e sincronização automática com o sistema Consinco (Oracle/PDV).

---

## Funcionalidades

### Gestão de Entregas
- Lançamento e acompanhamento de entregas em tempo real
- Status por etapas: pendente → em rota → finalizado
- Histórico completo por motorista, filial e período

### Gestão de Frota
- Cadastro e controle de veículos
- Registro de abastecimentos e custo por km (CPK)
- Controle de manutenções (solicitação, aprovação, histórico)
- Controle de pneus (instalação, descarte, vida útil)
- Alertas automáticos de manutenção e revisão

### Desempenho de Motoristas
- Score automático por turno (entregas, velocidade, ocorrências)
- Ranking geral de motoristas
- Histórico de turnos e checklists de veículo

### Integração Consinco
- Agente de sincronização automática (Oracle → Sistema Logístico)
- Importa pedidos de entrega do PDV a cada 30 segundos
- Cria clientes e entregas automaticamente, sem digitação manual

### Perfis de Acesso
| Perfil | Acesso |
|---|---|
| **Gestor** | Dashboard completo, frota, relatórios, gestão de usuários |
| **Operador** | Lançamento de entregas e clientes |
| **Entregador** | App mobile simplificado — turno, rotas e checklist |

---

## Tecnologias

| Camada | Tecnologia |
|---|---|
| Backend | FastAPI (Python) |
| Banco de dados | MySQL 8.0 + SQLAlchemy + Alembic |
| Templates | Jinja2 + Bootstrap / Tailwind CSS |
| Autenticação | Cookie HMAC-SHA256 |
| Sync Agent | Python + oracledb (Oracle thin mode) |
| Deploy | Docker + Docker Compose |

---

## Arquitetura

```
192.168.16.181  — Oracle/Consinco (PDV)
       ↑
       │ polling a cada 30s
       │
192.168.16.250  — Servidor principal
   ├── app         (FastAPI — porta 8000)
   ├── db          (MySQL 8.0)
   └── sync_agent  (Agente de sincronização)
```

---

## Como rodar

### Pré-requisitos
- Docker e Docker Compose instalados
- Acesso à rede onde o Oracle/Consinco está disponível

### 1. Clonar o repositório
```bash
git clone https://github.com/SEU_USUARIO/Sistema-logistico.git
cd Sistema-logistico
```

### 2. Configurar variáveis de ambiente
```bash
cp .env.example .env
```
Edite o `.env` com as credenciais reais (banco, Oracle, chave secreta).

### 3. Subir os serviços
```bash
docker compose up -d --build
```

O sistema estará disponível em `http://localhost:8000` (ou no IP do servidor).

### 4. Primeiro acesso
| Campo | Valor |
|---|---|
| Usuário | `admin` |
| Senha | definida no setup inicial |

---

## Estrutura do projeto

```
Sistema-logistico/
├── app/
│   ├── main.py          # Rotas FastAPI (78 endpoints)
│   ├── models.py        # Modelos SQLAlchemy
│   ├── database.py      # Conexão com MySQL
│   └── templates/       # Templates Jinja2 (26 telas)
├── alembic/             # Migrations do banco
├── sync_agent/
│   ├── consinco_sync.py # Agente de sincronização Oracle
│   └── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh        # Migrations + uvicorn
└── .env.example
```

---

## Comandos úteis

```bash
# Ver logs em tempo real
docker compose logs -f

# Reiniciar só a aplicação
docker compose restart app

# Reiniciar só o agente de sync
docker compose restart sync_agent

# Atualizar após mudanças no código
git pull && docker compose up -d --build
```

---

## Variáveis de ambiente

Veja o arquivo [`.env.example`](.env.example) para a lista completa de variáveis necessárias.

---

## Desenvolvedor

Desenvolvido por **Dyonathan Queiroz** — Auxiliar de T.I — Supermercado Gavião  
Boa Vista, Roraima
