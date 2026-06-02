"""
scraper/pdfs.py — Baixa os PDFs de exames de cada animal.

Lê animais.csv e baixa os laudos anexados. Laudos gerados por JavaScript
(imprimir_laudo_exame.php) são marcados como 'requer_navegador'.
Atualiza exames.csv com a coluna caminho_pdf.

Uso:  python -m scraper.pdfs
"""

import os
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup

import config
from .client import NuvemVetClient, salvar_csv, ler_csv, caminho_dado

PDF_DIR = os.path.join(config.OUTPUT_DIR, "exames_pdf")


def encontrar_links_pdf(tr_soup, base_url):
    """Retorna [(url, requer_navegador)] dos PDFs de uma linha de exame."""
    links, vistos = [], set()
    for a in tr_soup.find_all("a", href=True):
        href = a["href"]
        url = urljoin(base_url, href)
        if url in vistos:
            continue
        if "imprimir_laudo_exame" in href:          # gerado via JS
            links.append((url, True)); vistos.add(url); continue
        if href.lower().endswith(".pdf") or re.search(r"(download_exame|ver_exame)", href, re.I):
            links.append((url, False)); vistos.add(url); continue
        img = a.find("img")
        if img and re.search(r"pdf", str(img.get("src", "")) + str(img.get("alt", "")), re.I):
            if "imprimir" not in href.lower():
                links.append((url, False)); vistos.add(url)
    return links


def baixar_pdf(nv, url, caminho, tentativas=3):
    for i in range(tentativas):
        try:
            resp = nv.get(url, headers={"Accept": "application/pdf,*/*"})
            if resp is None or resp.status_code != 200:
                return False
            ct = resp.headers.get("Content-Type", "").lower()
            if "pdf" not in ct and not resp.content.startswith(b"%PDF"):
                return False
            with open(caminho, "wb") as f:
                f.write(resp.content)
            return True
        except Exception:
            if i == tentativas - 1:
                return False
    return False


def processar_animal(nv, base):
    """Processa exames de um animal. Retorna lista de registros."""
    soup = nv.get_soup("/admin/exame_animal_pdo.php",
                       params={"id_cliente": base["id_cliente"], "id_animal": base["id_animal"]})
    tabela = soup.find("table") if soup else None
    if not tabela:
        return []
    headers = [th.get_text(strip=True) for th in tabela.find_all("th")]
    registros = []
    for idx, tr in enumerate(tabela.find_all("tr")[1:], 1):
        cels = tr.find_all("td")
        if not cels:
            continue
        textos = [td.get_text(" ", strip=True) for td in cels]
        row = dict(zip(headers, textos)) if headers else {f"col_{i}": v for i, v in enumerate(textos)}
        row.update(base)
        row["caminho_pdf"] = ""
        row["url_pdf"] = ""

        links = encontrar_links_pdf(BeautifulSoup(str(tr), "html.parser"), f"{nv.base}/admin/")
        if links:
            url_pdf, requer_nav = links[0]
            row["url_pdf"] = url_pdf
            if requer_nav:
                row["caminho_pdf"] = "requer_navegador"
            else:
                nome_pdf = f"exame_{base['id_cliente']}_{base['id_animal']}_{idx}.pdf"
                caminho = os.path.join(PDF_DIR, nome_pdf)
                if os.path.exists(caminho):
                    row["caminho_pdf"] = caminho
                    print(f"      ↷ já existe: {nome_pdf}")
                elif baixar_pdf(nv, url_pdf, caminho):
                    row["caminho_pdf"] = caminho
                    print(f"      ✓ PDF salvo: {nome_pdf}")
                else:
                    print(f"      ✗ falhou: {url_pdf}")
        registros.append(row)
    return registros


def main():
    os.makedirs(PDF_DIR, exist_ok=True)
    nv = NuvemVetClient()
    if not nv.login():
        return

    animais = ler_csv("animais.csv")
    if not animais:
        print("✗ animais.csv não encontrado. Rode 'python -m scraper.clientes' antes.")
        return

    print(f"\nBaixando PDFs de exames para {len(animais)} animais...\n")
    todos = []
    for i, a in enumerate(animais, 1):
        base = {"id_cliente": a["id_cliente"], "id_animal": a["id_animal"],
                "nome_cliente": a.get("nome_cliente", ""), "nome_animal": a.get("nome_animal", "")}
        print(f"  [{i}/{len(animais)}] {base['nome_cliente']} → {base['nome_animal']}")
        todos.extend(processar_animal(nv, base))
        nv.sleep()

    salvar_csv("exames.csv", todos,
               ["id_cliente", "id_animal", "nome_cliente", "nome_animal", "caminho_pdf"])
    baixados = sum(1 for e in todos if e.get("caminho_pdf") and e["caminho_pdf"] != "requer_navegador")
    print(f"\n✓ Concluído! {baixados} PDFs em {PDF_DIR}")


if __name__ == "__main__":
    main()