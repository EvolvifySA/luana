"""
webapp — Aplicação Flask do Evolvify (Sistema Vet).

Cria a aplicação via factory create_app(). Lê dados locais (CSV + SQLite)
e não faz nenhuma requisição externa.
"""

import re

from flask import Flask, session
import config


def _data_br(valor):
    """Converte 'AAAA-MM-DD' (ISO, o que vem do banco/input date) pra 'DD/MM/AAAA'.

    Datas que já estiverem em outro formato (ou vazias) passam direto —
    isso só existe pra exibição, nunca pra alimentar um <input type="date">.
    """
    if not valor:
        return valor
    texto = str(valor)
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", texto)
    if m:
        ano, mes, dia = m.groups()
        return f"{dia}/{mes}/{ano}"
    return texto


def create_app():
    app = Flask(__name__)  # usa webapp/templates e webapp/static
    app.secret_key = config.SECRET_KEY
    app.jinja_env.filters["data_br"] = _data_br

    # Branding disponível em todos os templates
    @app.context_processor
    def injetar_branding():
        return {
            "APP_NOME":  config.APP_NOME,
            "APP_MARCA": config.APP_MARCA,
            "usuario_logado": session.get("usuario"),
        }

    from . import db
    db.init_app(app)

    from .routes import register_routes
    register_routes(app)

    return app