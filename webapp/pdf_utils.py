"""Helpers para gerar PDF real a partir dos templates do Flask."""

from __future__ import annotations

import base64
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from flask import current_app, render_template, send_file


@lru_cache(maxsize=1)
def logo_data_uri() -> str:
    logo_path = Path(__file__).resolve().parent / "static" / "logo.svg"
    if not logo_path.exists():
        return ""
    data = logo_path.read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _html_to_pdf_bytes(html: str) -> bytes:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright não está instalado. Rode `pip install -r requirements.txt` "
            "e `python -m playwright install chromium`."
        ) from exc

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ],
        )
        try:
            page = browser.new_page(
                viewport={"width": 1280, "height": 1800},
                device_scale_factor=1,
            )
            page.set_content(html, wait_until="networkidle")
            page.emulate_media(media="print")
            return page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "12mm", "right": "12mm", "bottom": "12mm", "left": "12mm"},
            )
        finally:
            browser.close()


def render_pdf_response(template_name: str, download_name: str, **context):
    html = render_template(template_name, **context)
    pdf_bytes = _html_to_pdf_bytes(html)
    buffer = BytesIO(pdf_bytes)
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=False,
        download_name=download_name,
        max_age=0,
    )


def pdf_context(**kwargs):
    """Contexto padrão para tickets/receitas em PDF e preview HTML."""
    return {
        "logo_src": logo_data_uri(),
        **kwargs,
    }

