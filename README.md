# Sistema Logístico

Sistema de gestão de entregas com dashboard web (FastAPI) e aplicativo PDV desktop (PyQt6).

## Tecnologias

- **Backend:** FastAPI + SQLAlchemy + MySQL
- **Frontend:** Jinja2 + AdminLTE 3 + Bootstrap 4
- **PDV Desktop:** PyQt6 + win32print (Windows)
- **Migrações:** Alembic
- **Autenticação:** bcrypt + cookies de sessão

## Pré-requisitos

- Python 3.11+
- MySQL 8.0+ rodando localmente
- Windows (para o módulo PDV com impressão térmica)

## Instalação

### 1. Clone o repositório

```bash
git clone https://github.com/seu-usuario/sistema-logistico.git
cd sistema-logistico
```

### 2. Crie e ative o ambiente virtual

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / macOS
source venv/bin/activate
```

### 3. Instale as dependências

```bash
pip install -r requirements.txt
```

### 4. Configure as variáveis de ambiente

```bash
cp .env.example .env
```

Edite o arquivo `.env` e preencha com seus dados:

```env
DATABASE_URL=mysql+pymysql://root:SUA_SENHA@localhost:3306/sistema_logistico
SECRET_KEY=gere_uma_chave_segura_aqui
```

Para gerar uma `SECRET_KEY` segura:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 5. Crie o banco de dados

No MySQL, execute:

```sql
CREATE DATABASE sistema_logistico CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 6. Execute as migrações

```bash
alembic upgrade head
```

> **Atenção:** Se precisar adicionar a coluna `motivo_erro` manualmente em instalações existentes:
> ```sql
> ALTER TABLE entregas ADD COLUMN motivo_erro TEXT NULL;
> ```

### 7. Inicie o servidor

```bash
uvicorn app.main:app --reload
```

O sistema estará disponível em: [http://127.0.0.1:8000](http://127.0.0.1:8000)

## Perfis de Acesso

| Perfil | Acesso |
|--------|--------|
| `gestor` | Dashboard completo, gestão de clientes, funcionários, veículos, filiais |
| `operador` | Dashboard (somente leitura) + lançamento via PDV |
| `entregador` | Painel mobile de aceite e finalização de entregas |

## Módulo PDV (Desktop)

O aplicativo PDV fica em `pdv_gui/` e é iniciado separadamente:

```bash
python -m pdv_gui
```

- **F10** — Abre a janela do PDV
- **F1** — Abre o formulário de lançamento de entrega
- **F2** — Confirma e imprime o cupom
- **F5** — Cadastrar novo cliente
- **ESC** — Minimiza para a bandeja do sistema

> Requer impressora térmica ESC/POS configurada no Windows.

## Estrutura do Projeto

```
sistema-logistico/
├── app/
│   ├── main.py          # Rotas FastAPI
│   ├── models.py        # Modelos SQLAlchemy
│   ├── database.py      # Conexão com o banco
│   ├── static/          # Assets AdminLTE
│   └── templates/       # Templates Jinja2
├── alembic/             # Migrações do banco
├── pdv_gui/             # Aplicativo PDV desktop
├── .env.example         # Template de variáveis de ambiente
├── requirements.txt     # Dependências Python
└── alembic.ini          # Configuração do Alembic
```

## Variáveis de Ambiente

| Variável | Descrição | Obrigatória |
|----------|-----------|:-----------:|
| `DATABASE_URL` | URL de conexão MySQL | ✅ |
| `SECRET_KEY` | Chave para segurança da aplicação | ✅ |
