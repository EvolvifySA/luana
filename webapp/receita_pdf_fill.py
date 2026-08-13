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

TEMPLATE_PATH = Path(__file__).resolve().parent / "static" / "receita_simples_template.pdf"

WINE = (0x5c / 255, 0x23 / 255, 0x46 / 255)
INK = (0x2a / 255, 0x2a / 255, 0x2a / 255)
# Cor de fundo da folha (medida direto no PDF, área da assinatura) — usada
# pra "apagar" o texto original sem deixar um retângulo branco destacado
# em cima da pata d'água (que é bem mais clara que branco puro).
BG = (239 / 255, 240 / 255, 240 / 255)

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


def _wrap_lines(text, fontname, fontsize, max_width):
    """Quebra o texto em linhas que cabem em max_width — palavra por palavra
    (sem cortar/esconder nada, diferente de só encolher a fonte numa linha)."""
    palavras = text.split()
    linhas, atual = [], ""
    for palavra in palavras:
        candidato = f"{atual} {palavra}".strip()
        if fitz.get_text_length(candidato, fontname=fontname, fontsize=fontsize) <= max_width:
            atual = candidato
        else:
            if atual:
                linhas.append(atual)
            atual = palavra
    if atual:
        linhas.append(atual)
    return linhas or [""]


def _place_wrapped(page, x, y_baseline, text, *, fontsize=10, fontname=FONT_REGULAR,
                    color=INK, max_width, line_height=None):
    """Como _place, mas quebra em várias linhas em vez de cortar. Retorna o
    y logo após a última linha desenhada."""
    if not text:
        return y_baseline
    line_height = line_height or fontsize * 1.25
    for linha in _wrap_lines(str(text), fontname, fontsize, max_width):
        page.insert_text((x, y_baseline), linha, fontsize=fontsize, fontname=fontname, color=color)
        y_baseline += line_height
    return y_baseline


def _place_centered(page, cx, y_baseline, text, *, fontsize=13, fontname=FONT_BOLD,
                     color=WINE, underline=False):
    width = fitz.get_text_length(text, fontname=fontname, fontsize=fontsize)
    page.insert_text((cx - width / 2, y_baseline), text, fontsize=fontsize, fontname=fontname, color=color)
    if underline:
        page.draw_line((cx - width / 2, y_baseline + 2), (cx + width / 2, y_baseline + 2), color=WINE, width=0.6)


def _preencher_cabecalho(page, cliente, animal, receita):
    """Escreve Responsável / Animal / Data da receita numa página do modelo."""
    # As coordenadas (x, baseline) e o corpo 9.6 vieram do span['origin'] real
    # de receita-exemplo-certo-comalgo.pdf — é o que alinha o valor com o
    # rótulo já impresso. Usar o topo/rodapé do bbox joga o texto ~2pt
    # pra baixo e deixa tudo torto.
    VAL = 9.6

    # Os x abaixo já respeitam ~3pt depois de onde cada rótulo do modelo
    # termina — os rótulos do PDF em branco são um pouco mais largos que os
    # do exemplo preenchido, então usar o x do exemplo cola o valor no rótulo
    # (e no caso de "Celular:" chegava a sobrepor).

    # ---- Responsável ----  (baselines 134.8 / 147.0 / 161.8)
    _place(page, 82.5, 134.8, cliente.get("nome", ""), fontsize=VAL, max_width=170)
    cpf = cliente.get("cpf") or ""
    if "inválido" in str(cpf):
        cpf = ""
    _place(page, 284.8, 134.8, cpf, fontsize=VAL, max_width=76)
    _place(page, 405.3, 134.8, cliente.get("celular", ""), fontsize=VAL, max_width=175)

    _place(page, 99.3, 147.0, cliente.get("endereco", ""), fontsize=VAL, max_width=155)
    _place(page, 276.3, 147.0, cliente.get("numero", ""), fontsize=VAL, max_width=82)
    _place(page, 389.2, 147.0, cliente.get("cep", ""), fontsize=VAL, max_width=190)

    _place(page, 80.0, 161.8, cliente.get("bairro", ""), fontsize=VAL, max_width=175)
    _place(page, 297.9, 161.8, cliente.get("cidade", ""), fontsize=VAL, max_width=64)
    _place(page, 403.7, 161.8, cliente.get("estado", ""), fontsize=VAL, max_width=185)

    # ---- Animal ----  (baselines 206.8 / 224.0)
    nome_animal = animal.get("nome_animal") or animal.get("nome") or ""
    _place(page, 81.5, 206.8, nome_animal, fontsize=VAL, max_width=137)
    _place(page, 261.5, 206.8, animal.get("especie", ""), fontsize=VAL, max_width=60)
    _place(page, 354.6, 206.8, animal.get("raca", ""), fontsize=VAL, max_width=100)
    _place(page, 489.5, 206.8, animal.get("sexo", ""), fontsize=VAL, max_width=67)

    _place(page, 91.4, 224.0, animal.get("pelagem", ""), fontsize=VAL, max_width=130)
    peso = animal.get("peso", "")
    if peso:
        peso = f"{peso} kg"
    _place(page, 252.0, 224.0, peso, fontsize=VAL, max_width=66)

    idade_txt = ""
    if animal.get("nascimento"):
        idade_txt = _data_br(animal["nascimento"])
        if animal.get("idade"):
            idade_txt = f"{idade_txt} ({animal['idade']})"
    _place(page, 355.4, 224.0, idade_txt, fontsize=VAL, max_width=100)

    castrado = animal.get("castrado_label") or animal.get("castrado") or ""
    _place(page, 508.1, 224.0, castrado, fontsize=VAL, max_width=56)

    # ---- Data da receita ----  (baseline 265.5)
    _place(page, 125.1, 265.5, receita.get("data", ""), fontsize=10, fontname=FONT_BOLD, color=WINE, max_width=430)


def _reescrever_assinatura(page, receita):
    """O modelo já traz "Luana Maria Feitosa Barroso / Médica veterinária /
    CRMV - PB 02956" na posição certa — só cobrimos e reescrevemos se a
    receita for de outro(a) profissional, nas mesmas baselines do original."""
    vet = (receita.get("veterinario") or "").strip()
    if not vet or vet == "Luana Maria Feitosa Barroso":
        return
    crmv = (receita.get("crmv") or "").strip()
    page.draw_rect(fitz.Rect(309, 588, 578, 632), color=BG, fill=BG)
    _place_centered(page, 458.8, 598.5, vet, fontsize=9.1, fontname=FONT_BOLD)
    _place_centered(page, 458.8, 611.3, "Médica veterinária", fontsize=10,
                     fontname=FONT_REGULAR, color=WINE)
    if crmv:
        _place_centered(page, 458.8, 625.5, crmv, fontsize=10,
                         fontname=FONT_REGULAR, color=WINE)


# Medidas do exemplo real (receita-exemplo-certo-comalgo.pdf): título "USO ORAL"
# centrado em x=274.2 na baseline 292.5 (corpo 12, sublinhado em +1.2); 1º
# medicamento na baseline 348.9 (corpo 9.3), régua começando 6.5pt depois do
# nome; posologia 30.8pt abaixo, x=63.8, corpo 10.
TIT_CX, MED_X, INSTR_X, QTD_DIR = 274.2, 51.8, 63.8, 534.0
Y_PRIMEIRO_TITULO = 292.5
# O traço da assinatura fica em y=584.1 — o conteúdo tem que parar antes disso,
# senão sai escrito por cima do nome da veterinária.
Y_LIMITE = 574.0

# Vãos do exemplo original (1 medicamento só, por isso tão folgados) e o mínimo
# aceitável. Tudo tem que caber numa folha só, então quando a receita cresce
# esses vãos vão sendo espremidos entre o "cheio" e o "mínimo".
GAP_TIT_ANTES, GAP_TIT_ANTES_MIN = 56.4, 18.0
GAP_TIT_DEPOIS, GAP_TIT_DEPOIS_MIN = 56.4, 20.0
GAP_ITEM, GAP_ITEM_MIN = 18.0, 14.0  # <14 a régua do item seguinte corta a posologia do anterior
GAP_NOME_INSTR, GAP_NOME_INSTR_MIN = 18.8, 15.0
GAP_OBS, GAP_OBS_MIN = 20.0, 12.0

# Ordem em que os vãos são espremidos quando a receita cresce: primeiro o
# espaço decorativo em volta dos títulos, por último o de dentro do
# medicamento (nome -> posologia), que é o que mais atrapalha a leitura.
PRIORIDADE_APERTO = ["tit_depois", "tit_antes", "obs", "item", "nome_instr"]


# Corpos do exemplo original e o menor aceitável — encolher a fonte é o
# último recurso pra manter a receita numa folha só.
FS_NOME, FS_INSTR, FS_OBS = 9.3, 10.0, 9.5
LH_NOME, LH_INSTR, LH_OBS = 11.6, 12.5, 12.5
ESCALA_MIN = 0.86


def _altura_necessaria(secoes, obs_linhas, g, esc=1.0):
    """Altura total do corpo (medicamentos + observações) com os vãos `g`."""
    total = 0.0
    for i, (itens, _titulo) in enumerate(secoes):
        if i:  # a 1ª seção já começa em Y_PRIMEIRO_TITULO
            total += g["tit_antes"]
        total += g["tit_depois"]
        for linhas_nome, linhas_instr in itens:
            total += len(linhas_nome) * LH_NOME * esc
            if linhas_instr:
                total += g["nome_instr"] + len(linhas_instr) * LH_INSTR * esc
            total += g["item"]
    if obs_linhas:
        total += g["obs"] + 15 + len(obs_linhas) * LH_OBS * esc
    return total


def gerar_receita_pdf_bytes(receita: dict, cliente: dict | None, animal: dict | None) -> bytes:
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Modelo não encontrado: {TEMPLATE_PATH}")

    cliente = cliente or {}
    animal = animal or {}

    doc = fitz.open(TEMPLATE_PATH)
    page = doc[0]
    _preencher_cabecalho(page, cliente, animal, receita)

    oral = receita.get("oral_itens") or []
    topico = receita.get("topico_itens") or []

    # --- pré-medição: quebra os textos e mede quanto o corpo vai ocupar ---
    def _preparar(itens, esc):
        preparados = []
        for item in itens:
            qtd = str(item.get("qtd", "") or "")
            qtd_w = fitz.get_text_length(qtd, fontname=FONT_REGULAR,
                                         fontsize=FS_INSTR * esc) if qtd else 0
            px = MED_X + fitz.get_text_length("00 - ", fontname=FONT_REGULAR,
                                              fontsize=FS_NOME * esc)
            largura_nome = (QTD_DIR - qtd_w - 12) - px
            linhas_nome = _wrap_lines(item.get("nome", ""), FONT_REGULAR,
                                      FS_NOME * esc, largura_nome)
            instr = item.get("instr", "")
            linhas_instr = _wrap_lines(instr, FONT_REGULAR, FS_INSTR * esc, 470) if instr else []
            preparados.append((linhas_nome, linhas_instr))
        return preparados

    obs_bruto = [l.strip().lstrip("-•").strip()
                 for l in (receita.get("observacao") or "").strip().splitlines()]
    obs_bruto = [l for l in obs_bruto if l]

    disponivel = Y_LIMITE - Y_PRIMEIRO_TITULO
    cheio = {"tit_antes": GAP_TIT_ANTES, "tit_depois": GAP_TIT_DEPOIS,
             "item": GAP_ITEM, "nome_instr": GAP_NOME_INSTR, "obs": GAP_OBS}
    minimo = {"tit_antes": GAP_TIT_ANTES_MIN, "tit_depois": GAP_TIT_DEPOIS_MIN,
              "item": GAP_ITEM_MIN, "nome_instr": GAP_NOME_INSTR_MIN, "obs": GAP_OBS_MIN}

    def _montar(esc):
        secoes = [(s, t) for s, t in ((_preparar(oral, esc), "USO ORAL"),
                                      (_preparar(topico, esc), "USO TÓPICO")) if s]
        obs_linhas = []
        for linha in obs_bruto:
            obs_linhas.extend(_wrap_lines(f"• {linha}", FONT_REGULAR, FS_OBS * esc, 500))
        return secoes, obs_linhas

    # Encolher a fonte é o último recurso: só entra se, mesmo com todos os
    # vãos no mínimo, o conteúdo não couber na folha.
    esc = 1.0
    for passo in range(8):
        cand = 1.0 - passo * ((1.0 - ESCALA_MIN) / 7)
        secoes, obs_linhas = _montar(cand)
        if _altura_necessaria(secoes, obs_linhas, minimo, cand) <= disponivel:
            esc = cand
            break
        esc = cand
    secoes, obs_linhas = _montar(esc)

    # Com a escala definida, devolve o máximo de respiro que ainda cabe,
    # apertando um vão de cada vez na ordem de prioridade.
    g = dict(cheio)
    for chave in PRIORIDADE_APERTO:
        if _altura_necessaria(secoes, obs_linhas, g, esc) <= disponivel:
            break
        g[chave] = minimo[chave]
        if _altura_necessaria(secoes, obs_linhas, g, esc) <= disponivel:
            lo, hi = minimo[chave], cheio[chave]
            for _ in range(24):
                meio = (lo + hi) / 2
                g[chave] = meio
                if _altura_necessaria(secoes, obs_linhas, g, esc) <= disponivel:
                    lo = meio
                else:
                    hi = meio
            g[chave] = lo
            break

    # --- desenho ---
    fs_nome, fs_instr, fs_obs = FS_NOME * esc, FS_INSTR * esc, FS_OBS * esc
    lh_nome, lh_instr, lh_obs = LH_NOME * esc, LH_INSTR * esc, LH_OBS * esc

    y = Y_PRIMEIRO_TITULO
    for i, (itens, titulo) in enumerate(secoes):
        if i:
            y += g["tit_antes"]
        _place_centered(page, TIT_CX, y, titulo, fontsize=12,
                         fontname=FONT_REGULAR, underline=True)
        y += g["tit_depois"]

        origem = oral if titulo == "USO ORAL" else topico
        for idx, (linhas_nome, linhas_instr) in enumerate(itens, start=1):
            qtd = str(origem[idx - 1].get("qtd", "") or "")
            qtd_w = fitz.get_text_length(qtd, fontname=FONT_REGULAR, fontsize=fs_instr) if qtd else 0
            qtd_x = QTD_DIR - qtd_w

            # Hífen simples: o travessão "–" não existe na Helvetica base-14
            # do PyMuPDF e sai como "·".
            prefixo = f"{idx} - "
            _place(page, MED_X, y, prefixo, fontsize=fs_nome, color=INK)
            px = MED_X + fitz.get_text_length(prefixo, fontname=FONT_REGULAR, fontsize=fs_nome)

            y_nome = y
            for linha in linhas_nome:
                _place(page, px, y_nome, linha, fontsize=fs_nome)
                y_nome += lh_nome
            y_ultima = y + (len(linhas_nome) - 1) * lh_nome

            if qtd:
                nome_w = fitz.get_text_length(linhas_nome[-1] if linhas_nome else "",
                                              fontname=FONT_REGULAR, fontsize=fs_nome)
                page.draw_line((px + nome_w + 6.5, y_ultima + 1), (qtd_x - 4, y_ultima + 1),
                               color=(0.5, 0.35, 0.4), width=0.5)
                _place(page, qtd_x, y_ultima, qtd, fontsize=fs_instr)

            y = y_ultima  # baseline da última linha do nome
            if linhas_instr:
                y += g["nome_instr"]
                for linha in linhas_instr:
                    _place(page, INSTR_X, y, linha, fontsize=fs_instr, color=INK)
                    y += lh_instr
                y -= lh_instr
            y += g["item"]

    if not secoes:
        _place_centered(page, TIT_CX, 348.9, "Nenhum medicamento informado.", fontsize=11,
                         fontname=FONT_REGULAR, color=(0.6, 0.6, 0.6))

    if obs_linhas:
        y += g["obs"]
        _place(page, 48.4, y, "Observações:", fontsize=10, fontname=FONT_BOLD, color=WINE)
        y += 15
        for linha in obs_linhas:
            _place(page, 58, y, linha, fontsize=fs_obs)
            y += lh_obs

    _reescrever_assinatura(page, receita)

    out = doc.tobytes(deflate=True)
    doc.close()
    return out
