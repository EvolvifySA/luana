"""WSGI entrypoint para rodar o Evolvify com Gunicorn."""

from webapp import create_app

app = create_app()

