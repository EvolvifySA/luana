#!/usr/bin/env python3
"""
URGENTE: Puxa CPF, celular, telefone, email e endereço de cada cliente.
Rode AGORA enquanto ainda tem acesso ao NuvemVet.
Gera: dados_exportados/clientes_cadastro.csv
"""

import requests
from bs4 import BeautifulSoup
import csv
import time
import os

import config

BASE  = config.BASE_URL
DELAY = 0.5


def criar_sessao():
    s = requests.Session()
    s.headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
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
    for campo in ["email", "usuario", "login"]:
        if campo in data:
            data[campo] = config.EMAIL; break
    else:
        data["email"] = config.EMAIL
    for campo in ["senha", "password"]:
        if campo in data:
            data[campo] = config.SENHA; break
    else:
        data["senha"] = config.SENHA
    s.post(action, data=data, allow_redirects=True)
    check = s.get(f"{BASE}/admin/dashboard.php", allow_redirects=True)
    if "dashboard" in check.url:
        print("✓ Login OK")
        return True
    print("✗ Login falhou")
    return False


def ler_ids_clientes():
    path = os.path.join(config.OUTPUT_DIR, "clientes.csv")
    ids = []
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ids.append((row["id_cliente"], row["nome"]))
    return ids


def extrair_pares(soup):
    """Extrai pares label:valor de qualquer estrutura de tabela ou lista."""
    dados = {}
    campos_quero = {
        "cpf", "celular", "telefone", "email", "endereço", "endereco",
        "cidade", "estado", "bairro", "cep", "nascimento",
        "como nos conheceu", "observação", "observacao",
        "whatsapp", "nome completo", "nome"
    }

    # Pares em <tr><th>/<td>
    for tr in soup.find_all("tr"):
        ths = tr.find_all(["th", "td"])
        if len(ths) == 2:
            k = ths[0].get_text(strip=True).lower().rstrip(":")
            v = ths[1].get_text(strip=True)
            if any(c in k for c in campos_quero) and v:
                dados[k] = v

    # Pares em <label>/<input> ou <label>/<span>
    for label in soup.find_all("label"):
        k = label.get_text(strip=True).lower().rstrip(":")
        if not any(c in k for c in campos_quero):
            continue
        # Tenta pegar valor do próximo sibling ou do input referenciado
        for_id = label.get("for")
        if for_id:
            el = soup.find(id=for_id)
            if el:
                v = el.get("value", "") or el.get_text(strip=True)
                if v:
                    dados[k] = v

    # Divs com classe que sugere campo
    for div in soup.find_all(["div", "span", "p"]):
        texto = div.get_text(separator=" ", strip=True)
        for campo in campos_quero:
            if texto.lower().startswith(campo + ":"):
                v = texto[len(campo)+1:].strip()
                if v:
                    dados[campo] = v
                break

    return dados


def get_cadastro(s, id_cliente):
    """Tenta buscar dados cadastrais do cliente em várias URLs possíveis."""
    urls = [
        f"{BASE}/admin/cadastro_cliente.php?id_cliente={id_cliente}",
        f"{BASE}/admin/visualizar_perfil_completo_cliente.php?id_cliente={id_cliente}",
        f"{BASE}/admin/editar_cliente.php?id_cliente={id_cliente}",
    ]
    for url in urls:
        try:
            resp = s.get(url, timeout=(10, 30))
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            dados = extrair_pares(soup)
            if dados:
                return dados
        except Exception:
            continue
    return {}


def main():
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    s = criar_sessao()
    if not login(s):
        return

    clientes = ler_ids_clientes()
    total    = len(clientes)
    print(f"\n{total} clientes para processar...\n")

    saida   = os.path.join(config.OUTPUT_DIR, "clientes_cadastro.csv")
    campos  = ["id_cliente", "nome", "cpf", "celular", "telefone",
               "email", "endereço", "cidade", "cep", "nascimento", "observação"]

    with open(saida, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        writer.writeheader()

        for i, (id_c, nome) in enumerate(clientes, 1):
            print(f"  [{i}/{total}] {nome}")
            dados = get_cadastro(s, id_c)
            dados["id_cliente"] = id_c
            dados["nome"]       = nome
            writer.writerow(dados)
            f.flush()  # salva linha por linha — se travar não perde nada
            time.sleep(DELAY)

    print(f"\n✓ Salvo em: {saida}")


if __name__ == "__main__":
    main()
