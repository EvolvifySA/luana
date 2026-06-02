"""
scraper — Ferramentas de extração de dados do NuvemVet.

Cada módulo coleta uma parte e salva em CSV em DATA_DIR.
Todos usam o cliente compartilhado de client.py (login, sessão, retry).

Uso (a partir da raiz do projeto):
    python -m scraper.clientes
    python -m scraper.pdfs
    python -m scraper.vacinas
    python -m scraper.tickets
    python -m scraper.animais_detalhes
    python -m scraper.cadastro_clientes
    python -m scraper.secoes
"""