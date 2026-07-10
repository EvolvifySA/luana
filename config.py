"""
config.py — Configuração central, carregada do arquivo .env.

Nenhuma credencial fica hardcoded aqui. Copie .env.example para .env
e preencha com seus valores.
"""

import os

# Carrega o .env, se python-dotenv estiver instalado
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Fallback: lê o .env manualmente (sem dependência externa)
    _env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(_env_path):
        with open(_env_path, encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip())


def _get(chave, padrao=""):
    return os.environ.get(chave, padrao)


# ─── NuvemVet (scrapers) ──────────────────────────────────────
EMAIL     = _get("NUVEMVET_EMAIL")
SENHA     = _get("NUVEMVET_SENHA")
BASE_URL  = _get("NUVEMVET_BASE_URL", "https://sistema.nuvemvet.com")
LOGIN_URL = _get("NUVEMVET_LOGIN_URL", "https://www.nuvemvet.com/entrar")

# ─── Dados ────────────────────────────────────────────────────
OUTPUT_DIR = _get("DATA_DIR", "dados_exportados")

# ─── Scraper ──────────────────────────────────────────────────
DELAY = float(_get("SCRAPER_DELAY", "0.8"))
LIMIT = int(_get("SCRAPER_LIMIT", "500"))

# ─── Web app (Evolvify) ───────────────────────────────────────
SECRET_KEY = _get("SECRET_KEY", "dev-secret-trocar")
FLASK_PORT = int(_get("FLASK_PORT", "5001"))
FLASK_DEBUG = _get("FLASK_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}
DATABASE_URL = _get("DATABASE_URL", "")
# Máximo de conexões no pool por processo (gunicorn worker). Como cada
# requisição usa 1 conexão e há ~4 threads/worker, 8 cobre com folga.
PG_POOL_MAX = int(_get("PG_POOL_MAX", "8"))
SUPABASE_URL = _get("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = _get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_STORAGE_BUCKET = _get("SUPABASE_STORAGE_BUCKET", "")
DEFAULT_ADMIN_EMAIL = _get("DEFAULT_ADMIN_EMAIL", "")

APP_NOME  = "Sistema Vet"
APP_MARCA = "Evolvify Vet"

CLINICA = {
    "nome":     _get("CLINICA_NOME", "Luana Feitosa — Atendimento Domiciliar"),
    "tel1":     _get("CLINICA_TEL", ""),
    "tel2":     "",
    "email":    _get("CLINICA_EMAIL", ""),
    "cidade":   _get("CLINICA_CIDADE", ""),
    "endereco": "",
    "cep":      "",
    "cnpj":     "",
}
