"""Gera o Receituário Simples preenchendo o PDF de referência da própria
Luana (receita/receitasimples.pdf) em vez de reconstruir o layout em HTML —
garante que o fundo, as linhas, a logo e a assinatura saiam pixel-perfeitos,
porque é literalmente o arquivo que ela desenhou.

As coordenadas abaixo foram extraídas com PyMuPDF direto de
receita/receitasimples.pdf (em branco) e receita/receitasimplescomalgo.pdf
(preenchido), pegando a posição real de cada rótulo/valor no PDF.
"""

from __future__ import annotations

import re
from pathlib import Path

import fitz  # PyMuPDF


def _data_br(valor):
    """Mesma conversão 'AAAA-MM-DD' -> 'DD/MM/AAAA' do filtro Jinja data_br
    (webapp/__init__.py) — duplicada aqui pra não puxar import circular."""
    if not valor:
        return valor
    texto = str(valor)
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", texto)
    if m:
        ano, mes, dia = m.groups()
        return f"{dia}/{mes}/{ano}"
    return texto

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "receita" / "receitasimples.pdf"

WINE = (0x5c / 255, 0x23 / 255, 0x46 / 255)
INK = (0x2a / 255, 0x2a / 255, 0x2a / 255)

FONT_REGULAR = "helv"
FONT_BOLD = "hebo"


def _fit_fontsize(page, text, fontname, start_size, max_width, min_size=6.5):
    """Reduz a fonte até o texto caber em max_width (evita invadir o próximo campo)."""
    size = start_size
    while size > min_size:
        width = fitz.get_text_length(text, fontname=fontname, fontsize=size)
        if width <= max_width:
            return size
        size -= 0.5
    return min_size


def _place(page, x, y_baseline, text, *, fontsize=10, fontname=FONT_REGULAR,
           color=INK, max_width=None):
    if not text:
        return
    text = str(text)
    if max_width:
        fontsize = _fit_fontsize(page, text, fontname, fontsize, max_width)
    page.insert_text((x, y_baseline), text, fontsize=fontsize, fontname=fontname, color=color)


def _place_centered(page, cx, y_baseline, text, *, fontsize=13, fontname=FONT_BOLD,
                     color=WINE, underline=False):
    width = fitz.get_text_length(text, fontname=fontname, fontsize=fontsize)
    page.insert_text((cx - width / 2, y_baseline), text, fontsize=fontsize, fontname=fontname, color=color)
    if underline:
        page.draw_line((cx - width / 2, y_baseline + 2), (cx + width / 2, y_baseline + 2), color=WINE, width=0.6)


def gerar_receita_pdf_bytes(receita: dict, cliente: dict | None, animal: dict | None) -> bytes:
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Modelo não encontrado: {TEMPLATE_PATH}")

    cliente = cliente or {}
    animal = animal or {}

    doc = fitz.open(TEMPLATE_PATH)
    page = doc[0]

    GAP = 4  # respiro entre o rótulo (já impresso no PDF) e o valor

    # ---- Responsável ----
    _place(page, 81.6 + GAP, 136.8, cliente.get("nome", ""), max_width=170 - GAP)
    cpf = cliente.get("cpf") or ""
    if "inválido" in str(cpf):
        cpf = ""
    _place(page, 282.9 + GAP, 136.8, cpf, max_width=76 - GAP)
    _place(page, 401.7 + GAP, 136.8, cliente.get("celular", ""), max_width=185 - GAP)

    _place(page, 98.4 + GAP, 149.0, cliente.get("endereco", ""), max_width=156 - GAP)
    _place(page, 275.1 + GAP, 149.0, cliente.get("numero", ""), max_width=85 - GAP)
    _place(page, 386.7 + GAP, 149.0, cliente.get("cep", ""), max_width=200 - GAP)

    _place(page, 80.0 + GAP, 163.9, cliente.get("bairro", ""), max_width=175 - GAP)
    _place(page, 297.9 + GAP, 163.9, cliente.get("cidade", ""), max_width=65 - GAP)
    _place(page, 403.7 + GAP, 163.9, cliente.get("estado", ""), max_width=190 - GAP)

    # ---- Animal ----
    nome_animal = animal.get("nome_animal") or animal.get("nome") or ""
    _place(page, 81.0 + GAP, 208.9, nome_animal, max_width=135 - GAP)
    _place(page, 261.5 + GAP, 208.9, animal.get("especie", ""), max_width=60 - GAP)
    _place(page, 352.5 + GAP, 208.9, animal.get("raca", ""), max_width=100 - GAP)
    _place(page, 488.5 + GAP, 208.9, animal.get("sexo", ""), max_width=65 - GAP)

    _place(page, 90.8 + GAP, 226.1, animal.get("pelagem", ""), max_width=130 - GAP)
    peso = animal.get("peso", "")
    if peso:
        peso = f"{peso} kg"
    _place(page, 249.9 + GAP, 226.1, peso, max_width=68 - GAP)

    idade_txt = ""
    if animal.get("nascimento"):
        idade_txt = _data_br(animal["nascimento"])
        if animal.get("idade"):
            idade_txt = f"{idade_txt} ({animal['idade']})"
    _place(page, 353.3 + GAP, 226.1, idade_txt, max_width=101 - GAP)

    castrado = animal.get("castrado_label") or animal.get("castrado") or ""
    _place(page, 505.8 + GAP, 226.1, castrado, max_width=55 - GAP)

    # ---- Data da receita ----
    _place(page, 125.1, 267.6, receita.get("data", ""), fontsize=10, fontname=FONT_BOLD, color=WINE, max_width=440)

    # ---- Medicamentos ----
    oral = receita.get("oral_itens") or []
    topico = receita.get("topico_itens") or []
    y = 295.0

    def _render_lista(itens, titulo, y):
        if not itens:
            return y
        y += 25
        _place_centered(page, 306, y, titulo, fontsize=13, underline=True)
        y += 30
        for idx, item in enumerate(itens, start=1):
            nome = item.get("nome", "")
            qtd = item.get("qtd", "")
            instr = item.get("instr", "")
            prefixo = f"{idx} - "
            _place(page, 51.8, y, prefixo, fontsize=11, color=INK)
            px = 51.8 + fitz.get_text_length(prefixo, fontname=FONT_REGULAR, fontsize=11)
            qtd_w = fitz.get_text_length(str(qtd), fontname=FONT_REGULAR, fontsize=10) if qtd else 0
            nome_max = 560 - qtd_w - 20 - px
            _place(page, px, y, nome, fontsize=11, max_width=nome_max)
            if qtd:
                page.draw_line((px, y + 2), (560 - qtd_w - 8, y + 2), color=(0.5, 0.35, 0.4), width=0.5)
                _place(page, 560 - qtd_w, y, qtd, fontsize=10)
            y += 20
            if instr:
                _place(page, 63.8, y, instr, fontsize=10, color=INK, max_width=480)
                y += 22
            y += 10
        return y

    y = _render_lista(oral, "USO ORAL", y)
    y = _render_lista(topico, "USO TÓPICO", y)

    if not oral and not topico:
        _place_centered(page, 306, y + 35, "Nenhum medicamento informado.", fontsize=11,
                         fontname=FONT_REGULAR, color=(0.6, 0.6, 0.6))

    # ---- Observações (ancoradas perto do rodapé, não coladas nos medicamentos) ----
    obs = (receita.get("observacao") or "").strip()
    if obs:
        obs_y = max(y + 20, 470)
        _place(page, 48.4, obs_y, "Observações:", fontsize=10, fontname=FONT_BOLD, color=WINE)
        obs_y += 15
        for linha in obs.splitlines():
            linha = linha.strip().lstrip("-•").strip()
            if not linha:
                continue
            _place(page, 58, obs_y, f"• {linha}", fontsize=9.5, max_width=500)
            obs_y += 13

    # ---- Assinatura / rodapé (já vêm desenhados no PDF de referência) ----
    vet = receita.get("veterinario") or ""
    crmv = receita.get("crmv") or ""
    if vet and vet != "Luana Maria Feitosa Barroso":
        page.draw_rect(fitz.Rect(391, 584, 528, 628), color=(1, 1, 1), fill=(1, 1, 1))
        _place_centered(page, 459, 600, vet, fontsize=12, fontname=FONT_BOLD)
        _place_centered(page, 459, 613, "Médica veterinária", fontsize=10, fontname=FONT_REGULAR, color=WINE)
        if crmv:
            _place_centered(page, 459, 627, crmv, fontsize=10, fontname=FONT_REGULAR, color=WINE)

    out = doc.tobytes(deflate=True)
    doc.close()
    return out
