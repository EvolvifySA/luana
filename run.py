"""
run.py — Ponto de entrada do Evolvify (Sistema Vet).

Uso:
    python run.py

Acesse em http://localhost:5001 (porta configurável no .env).
"""

from webapp import create_app
import config

app = create_app()

if __name__ == "__main__":
    print("=" * 52)
    print(f"  {config.APP_NOME} — {config.APP_MARCA}")
    print(f"  http://localhost:{config.FLASK_PORT}")
    print(f"  Dados locais: {config.OUTPUT_DIR}/")
    print("=" * 52)
    app.run(debug=False, port=config.FLASK_PORT)