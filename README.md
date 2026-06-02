# Sistema Vet — Evolvify

Sistema de gestão veterinária: clientes, animais, prontuários, tickets,
receituários e dashboard financeiro. Funciona **100% offline** com os dados
locais (CSV + SQLite).

---

## Estrutura do projeto

```
luana/
├── run.py                  # inicia a aplicação web
├── config.py               # configuração (lê do .env)
├── .env                    # credenciais e configs (NÃO versionar)
├── .env.example            # modelo do .env
├── requirements.txt
│
├── webapp/                 # aplicação web (Flask)
│   ├── __init__.py         #   create_app() — factory
│   ├── routes.py           #   todas as rotas
│   ├── db.py               #   camada de dados (CSV + SQLite)
│   ├── templates/          #   telas (Jinja2)
│   └── static/             #   CSS, JS, logo
│
├── scraper/                # extração de dados do NuvemVet
│   ├── client.py           #   cliente HTTP compartilhado (login, retry)
│   ├── clientes.py         #   clientes + animais + histórico
│   ├── pdfs.py             #   PDFs de exames
│   ├── vacinas.py          #   vacinas
│   ├── tickets.py          #   tickets + serviços
│   ├── animais_detalhes.py #   dados cadastrais dos animais
│   ├── cadastro_clientes.py#   CPF/contato dos clientes
│   └── secoes.py           #   receituário, anotações, cirurgias...
│
└── dados_exportados/       # dados locais (NÃO versionar — LGPD)
    └── exames_pdf/         # PDFs baixados
```

---

## Como rodar

### 1. Instalar dependências
```bash
pip install -r requirements.txt
```

### 2. Configurar o ambiente
```bash
cp .env.example .env
# edite o .env com suas credenciais e configurações
```

### 3. Iniciar o sistema
```bash
python run.py
```
Acesse **http://localhost:5001**

**Login padrão:** `luana` / `evolvify2026` (troque em *Conta* após entrar).

---

## Atualizar os dados (scrapers)

Os scrapers extraem dados do NuvemVet. Rode a partir da raiz do projeto:

```bash
python -m scraper.clientes           # clientes + animais + histórico
python -m scraper.animais_detalhes   # carteirinha, raça, sexo, etc.
python -m scraper.cadastro_clientes  # CPF, telefone, endereço
python -m scraper.vacinas            # histórico de vacinas
python -m scraper.pdfs               # PDFs de exames
python -m scraper.tickets            # tickets + catálogo de serviços
python -m scraper.secoes             # receituário, cirurgias, etc.
```

---

## Importante

- **Nunca versione** `dados_exportados/`, `.env` ou arquivos `.db` — contêm
  dados pessoais de clientes (LGPD) e credenciais.
- Em produção, os dados ficam no servidor/banco, nunca no repositório.
- A logo fica em `webapp/static/logo.svg`.