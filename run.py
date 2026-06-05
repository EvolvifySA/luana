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
    print(f"  Neste PC:   http://localhost:{config.FLASK_PORT}")
    print(f"  No celular: http://<IP-DO-PC>:{config.FLASK_PORT}  (mesmo Wi-Fi)")
    print(f"  Dados locais: {config.OUTPUT_DIR}/")
    print("=" * 52)
    # host="0.0.0.0" libera o acesso de outros aparelhos na mesma rede (ex: celular)
    app.run(debug=False, host="0.0.0.0", port=config.FLASK_PORT)