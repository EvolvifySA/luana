"""
webapp — Aplicação Flask do Evolvify (Sistema Vet).

Cria a aplicação via factory create_app(). Lê dados locais (CSV + SQLite)
e não faz nenhuma requisição externa.
"""

from flask import Flask, session
import config


def create_app():
    app = Flask(__name__)  # usa webapp/templates e webapp/static
    app.secret_key = config.SECRET_KEY

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