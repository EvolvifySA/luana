# Sistema Vet - Evolvify

Sistema de gestao veterinaria com clientes, animais, prontuarios, tickets,
receituarios e dashboard financeiro.

Hoje o projeto tem dois caminhos:
- modo local, com CSV + SQLite legado
- modo novo, com Postgres/Supabase e PDF real via Playwright

---

## Estrutura principal

```text
luana/
|-- run.py
|-- wsgi.py
|-- config.py
|-- requirements.txt
|-- Dockerfile
|-- docker-compose.yml
|-- .env.example
|-- webapp/
|-- scraper/
|-- scripts/
|-- supabase/
|-- dados_exportados/
```

---

## Como rodar localmente

### 1. Criar ambiente e instalar dependencias

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

### 2. Configurar o `.env`

```powershell
copy .env.example .env
```

Preencha:
- `SECRET_KEY`
- `DATABASE_URL`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_STORAGE_BUCKET`
- credenciais do NuvemVet, se for usar os scrapers

### 3. Subir o app

```powershell
python run.py
```

Abra:
- `http://localhost:5001`

---

## Docker na VPS

Este projeto foi preparado para rodar em VPS com Docker usando:
- `gunicorn` como servidor WSGI
- imagem oficial do Playwright com Chromium ja instalado
- Postgres do Supabase para banco

### Arquivos que sobem na VPS

Para subir o backend, voce precisa levar:
- `Dockerfile`
- `docker-compose.yml`
- `.env` na VPS, nao no repositório
- `requirements.txt`
- `run.py`
- `wsgi.py`
- `config.py`
- pasta `webapp/`
- pasta `scripts/` se for rodar migracao
- pasta `supabase/` se for aplicar o schema
- pasta `dados_exportados/` somente se ainda for usar arquivos locais

Voce nao precisa subir:
- `venv/`
- `.git/`
- `__pycache__/`
- `evolvify.db` para producao, se a base ja estiver no Supabase

### Build e start

```bash
docker compose up -d --build
```

Para ver os logs:

```bash
docker compose logs -f
```

Para parar:

```bash
docker compose down
```

---

## Variaveis de ambiente

### Segredos do backend

Use estas chaves no `.env` da VPS:
- `SECRET_KEY`: chave do Flask para sessoes e flash messages
- `DATABASE_URL`: string de conexao do Postgres do Supabase
- `SUPABASE_URL`: URL publica do projeto Supabase
- `SUPABASE_SERVICE_ROLE_KEY`: chave secreta do backend para Storage e operacoes administrativas
- `SUPABASE_STORAGE_BUCKET`: nome do bucket

### NuvemVet

Somente se voce for rodar os scrapers:
- `NUVEMVET_EMAIL`
- `NUVEMVET_SENHA`
- `NUVEMVET_BASE_URL`
- `NUVEMVET_LOGIN_URL`

### Clinica

Usadas nos tickets e receitas:
- `CLINICA_NOME`
- `CLINICA_TEL`
- `CLINICA_EMAIL`
- `CLINICA_CIDADE`

---

## Banco novo / Supabase

O schema PostgreSQL completo esta em `supabase/schema.sql`.

Para migrar os CSVs:

```bash
python scripts/migrate_csv_to_supabase.py --dry-run
python scripts/migrate_csv_to_supabase.py
```

---

## PDFs reais

Os PDFs de ticket e receita sao gerados no servidor via Playwright.
Os endpoints principais sao:
- `/ticket/<id>/pdf`
- `/receita/<id>/pdf`

---

## CORS

Se voce usar este backend Flask como site principal, **nao deve ter problema de CORS**.

Voce so precisa pensar em CORS se:
- um frontend separado em outro dominio fizer chamadas `fetch` para o backend
- um app externo consumir a API diretamente

No fluxo proposto aqui:
- o browser acessa o Flask
- o Flask acessa o Supabase no servidor
- logo, CORS nao entra no caminho do banco nem do Storage

---

## Comandos uteis na VPS

```bash
docker compose ps
docker compose logs -f app
docker exec -it <container> bash
```

---

## Observacao de producao

Para producao, use Nginx na frente do container e deixe o Docker expor a porta
`8000` internamente. O Nginx pode terminar TLS e encaminhar para o Gunicorn.
