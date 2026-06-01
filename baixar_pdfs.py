#!/usr/bin/env python3
"""
Baixa os PDFs de exames de cada animal e atualiza exames.csv com o caminho local.
Lê animais.csv (já gerado pelo scraper) para não precisar refazer tudo.
"""

import requests
from bs4 import BeautifulSoup
import csv
import time
import os
import re
from urllib.parse import urlparse, parse_qs, urljoin

import config

BASE      = config.BASE_URL
DELAY     = config.DELAY
PDF_DIR   = os.path.join(config.OUTPUT_DIR, "exames_pdf")
EXAMES_IN = os.path.join(config.OUTPUT_DIR, "exames.csv")
EXAMES_OUT= os.path.join(config.OUTPUT_DIR, "exames.csv")  # sobrescreve com coluna nova


# ─── SESSÃO / LOGIN ───────────────────────────────────────────────────────────

def criar_sessao():
    s = requests.Session()
    s.headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    return s


def login(s):
    print("Fazendo login...")
    resp = s.get(config.LOGIN_URL)
    soup = BeautifulSoup(resp.text, "html.parser")

    form   = soup.find("form")
    data   = {}
    action = config.LOGIN_URL

    if form:
        for inp in form.find_all("input"):
            n = inp.get("name")
            if n:
                data[n] = inp.get("value", "")
        act = form.get("action", "")
        if act:
            action = act if act.startswith("http") else "https://www.nuvemvet.com" + act

    for campo in ["email", "usuario", "login", "user"]:
        if campo in data:
            data[campo] = config.EMAIL
            break
    else:
        data["email"] = config.EMAIL

    for campo in ["senha", "password", "pass"]:
        if campo in data:
            data[campo] = config.SENHA
            break
    else:
        data["senha"] = config.SENHA

    s.post(action, data=data, allow_redirects=True)

    check = s.get(f"{BASE}/admin/dashboard.php", allow_redirects=True)
    if "dashboard" in check.url and "entrar" not in check.url:
        print("✓ Login OK")
        return True

    print(f"✗ Login falhou — verifique EMAIL e SENHA em config.py")
    return False


# ─── LER ANIMAIS ──────────────────────────────────────────────────────────────

def ler_animais():
    """Lê animais.csv e retorna lista de (id_cliente, id_animal, nome_cliente, nome_animal)."""
    path = os.path.join(config.OUTPUT_DIR, "animais.csv")
    if not os.path.exists(path):
        print(f"✗ Arquivo não encontrado: {path}")
        print("  Rode scraper.py primeiro.")
        return []

    animais = []
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            animais.append(row)
    print(f"  {len(animais)} animais encontrados em animais.csv")
    return animais


# ─── BAIXAR PDFS ──────────────────────────────────────────────────────────────

def get_com_retry(s, url, tentativas=3, **kwargs):
    """Faz GET com retry automático em caso de queda de conexão."""
    kwargs.setdefault("timeout", (10, 30))  # (connect, read) — não trava mais
    for tentativa in range(1, tentativas + 1):
        try:
            return s.get(url, **kwargs)
        except Exception as e:
            if tentativa < tentativas:
                print(f"      Conexão caiu ({e.__class__.__name__}), tentando novamente ({tentativa}/{tentativas})...")
                time.sleep(3)
            else:
                raise
    return None


def encontrar_links_pdf(soup, base_url):
    """
    Retorna lista de (url, requer_navegador) de PDFs encontrados na página.
    imprimir_laudo_exame.php precisa de navegador (JavaScript) — marcado como True.
    """
    links = []
    seen  = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        url  = urljoin(base_url, href)

        if url in seen:
            continue

        # Gerado via JS — não dá pra baixar com requests
        if "imprimir_laudo_exame" in href:
            links.append((url, True))
            seen.add(url)
            continue

        # Link direto para PDF ou download
        if (href.lower().endswith(".pdf") or
                re.search(r"(download_exame|ver_exame)", href, re.I)):
            links.append((url, False))
            seen.add(url)
            continue

        # Imagem de PDF dentro do link
        img = a.find("img")
        if img and re.search(r"pdf", str(img.get("src", "")) + str(img.get("alt", "")), re.I):
            if "imprimir" not in href.lower():
                links.append((url, False))
                seen.add(url)

    return links


def baixar_pdf(s, url, caminho, tentativas=3):
    """Baixa um PDF e salva no caminho indicado. Retorna True se OK."""
    for tentativa in range(1, tentativas + 1):
        try:
            resp = get_com_retry(s, url, headers={"Accept": "application/pdf,*/*"})
            if resp is None or resp.status_code != 200:
                return False

            ct       = resp.headers.get("Content-Type", "").lower()
            conteudo = resp.content

            if "pdf" not in ct and not conteudo.startswith(b"%PDF"):
                return False

            with open(caminho, "wb") as f:
                f.write(conteudo)
            return True

        except Exception as e:
            if tentativa < tentativas:
                time.sleep(3)
            else:
                print(f"    ✗ Falhou após {tentativas} tentativas: {e.__class__.__name__}")
                return False
    return False


def processar_exames_animal(s, id_cliente, id_animal, nome_cliente, nome_animal):
    """
    Acessa a página de exames do animal, encontra PDFs e baixa.
    Retorna lista de dicts com dados do exame + caminho_pdf local.
    """
    url = f"{BASE}/admin/exame_animal_pdo.php"
    try:
        resp = get_com_retry(s, url, params={"id_cliente": id_cliente, "id_animal": id_animal})
    except Exception as e:
        print(f"    ✗ Erro ao carregar exames: {e.__class__.__name__}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    registros = []
    tabela    = soup.find("table")
    if not tabela:
        return registros

    headers = [th.get_text(strip=True) for th in tabela.find_all("th")]

    for idx, tr in enumerate(tabela.find_all("tr")[1:], 1):
        cells = tr.find_all("td")
        if not cells:
            continue

        # Dados textuais da linha
        textos = [td.get_text(" ", strip=True) for td in cells]
        if headers:
            row = dict(zip(headers, textos))
        else:
            row = {"col_" + str(i): v for i, v in enumerate(textos)}

        row["id_cliente"]   = id_cliente
        row["id_animal"]    = id_animal
        row["nome_cliente"] = nome_cliente
        row["nome_animal"]  = nome_animal
        row["caminho_pdf"]  = ""

        # Procura link de PDF nessa linha
        links_pdf = encontrar_links_pdf(BeautifulSoup(str(tr), "html.parser"),
                                        f"{BASE}/admin/")
        if links_pdf:
            url_pdf, requer_navegador = links_pdf[0]
            if requer_navegador:
                # Gerado por JavaScript — não dá pra baixar automaticamente
                row["caminho_pdf"] = "requer_navegador"
                row["url_pdf"]     = url_pdf
            else:
                nome_pdf = f"exame_{id_cliente}_{id_animal}_{idx}.pdf"
                caminho  = os.path.join(PDF_DIR, nome_pdf)
                if os.path.exists(caminho):
                    row["caminho_pdf"] = caminho
                    row["url_pdf"]     = url_pdf
                    print(f"      ↷ Já existe: {nome_pdf}")
                else:
                    ok = baixar_pdf(s, url_pdf, caminho)
                    if ok:
                        row["caminho_pdf"] = caminho
                        row["url_pdf"]     = url_pdf
                        print(f"      ✓ PDF salvo: {nome_pdf}")
                    else:
                        row["url_pdf"] = url_pdf
                        print(f"      ✗ Falhou: {url_pdf}")

        registros.append(row)

    return registros


# ─── SALVAR CSV ───────────────────────────────────────────────────────────────

def salvar_csv(nome_arquivo, dados, campos_primeiro=None):
    if not dados:
        print(f"  (sem dados — {nome_arquivo})")
        return

    todos_campos = list(campos_primeiro or [])
    seen = set(todos_campos)
    for row in dados:
        for c in row:
            if c not in seen:
                todos_campos.append(c)
                seen.add(c)

    path = os.path.join(config.OUTPUT_DIR, nome_arquivo)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=todos_campos, extrasaction="ignore")
        w.writeheader()
        w.writerows(dados)

    print(f"  → {path}  ({len(dados)} linhas)")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(PDF_DIR, exist_ok=True)

    s = criar_sessao()
    if not login(s):
        return

    animais = ler_animais()
    if not animais:
        return

    print(f"\nBaixando PDFs de exames para {len(animais)} animais...\n")

    todos_exames = []
    total = len(animais)

    for i, animal in enumerate(animais, 1):
        id_c   = animal["id_cliente"]
        id_a   = animal["id_animal"]
        nome_c = animal.get("nome_cliente", "")
        nome_a = animal.get("nome_animal", "")

        print(f"  [{i}/{total}] {nome_c} → {nome_a}")

        exames = processar_exames_animal(s, id_c, id_a, nome_c, nome_a)
        todos_exames.extend(exames)

        if not exames:
            print("    (sem exames)")

        time.sleep(DELAY)

    salvar_csv(
        "exames.csv",
        todos_exames,
        ["id_cliente", "id_animal", "nome_cliente", "nome_animal", "caminho_pdf"],
    )

    pdfs_baixados = sum(1 for e in todos_exames if e.get("caminho_pdf"))
    print(f"\n✓ Concluído!")
    print(f"  PDFs baixados: {pdfs_baixados}")
    print(f"  Pasta dos PDFs: {PDF_DIR}")
    print(f"  CSV atualizado: {EXAMES_OUT}")


if __name__ == "__main__":
    main()
