#!/usr/bin/env python3
"""
puxar_tickets.py — Coleta catálogo de serviços e histórico de tickets.

URLs confirmadas por inspeção:
  Catálogo:  tipos_de_servicos.php            (169 serviços de clínica)
  Tickets:   tickets.php?id_cliente=X         (tabela de tickets do cliente)

Gera:
  dados_exportados/servicos.csv
  dados_exportados/tickets.csv
"""

import requests
from bs4 import BeautifulSoup
import csv, time, os, re
import config

BASE  = config.BASE_URL
DELAY = 0.4
SERVICOS_OUT = os.path.join(config.OUTPUT_DIR, "servicos.csv")
TICKETS_OUT  = os.path.join(config.OUTPUT_DIR, "tickets.csv")


def criar_sessao():
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    return s


def login(s):
    print("Fazendo login...")
    resp = s.get(config.LOGIN_URL)
    soup = BeautifulSoup(resp.text, "html.parser")
    form = soup.find("form"); data, action = {}, config.LOGIN_URL
    if form:
        for inp in form.find_all("input"):
            n = inp.get("name")
            if n: data[n] = inp.get("value", "")
        act = form.get("action", "")
        if act: action = act if act.startswith("http") else "https://www.nuvemvet.com" + act
    for c in ["email", "usuario"]:
        if c in data: data[c] = config.EMAIL; break
    else: data["email"] = config.EMAIL
    for c in ["senha", "password"]:
        if c in data: data[c] = config.SENHA; break
    else: data["senha"] = config.SENHA
    s.post(action, data=data, allow_redirects=True)
    ok = "dashboard" in s.get(f"{BASE}/admin/dashboard.php", allow_redirects=True).url
    print("✓ Login OK" if ok else "✗ Login falhou")
    return ok


def get_com_retry(s, url, **kwargs):
    kwargs.setdefault("timeout", (10, 30))
    for i in range(3):
        try: return s.get(url, **kwargs)
        except Exception:
            if i < 2: time.sleep(2)
            else: raise


# ─── CATÁLOGO DE SERVIÇOS ────────────────────────────────────────────────────

def scrape_servicos(s):
    print("\n[1/2] Coletando catálogo de serviços (clínica)...")
    resp = get_com_retry(s, f"{BASE}/admin/tipos_de_servicos.php")
    soup = BeautifulSoup(resp.text, "html.parser")
    tabela = soup.find("table")
    if not tabela:
        print("  ✗ Nenhuma tabela encontrada")
        return

    headers = [th.get_text(strip=True) for th in tabela.find_all("th")]
    servicos = []
    vistos   = set()
    for tr in tabela.find_all("tr")[1:]:
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if not any(cells):
            continue
        row = dict(zip(headers, cells)) if headers else {}
        nome = row.get("Nome do Serviço") or (cells[0] if cells else "")
        if nome in vistos:   # dedup
            continue
        vistos.add(nome)
        row["tipo"] = "clinica"
        servicos.append(row)

    if servicos:
        campos = list(servicos[0].keys())
        with open(SERVICOS_OUT, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
            w.writeheader(); w.writerows(servicos)
        print(f"  ✓ {len(servicos)} serviços únicos salvos em {SERVICOS_OUT}")


# ─── HISTÓRICO DE TICKETS ────────────────────────────────────────────────────

def scrape_tickets_cliente(s, id_cliente):
    """tickets.php?id_cliente=X — retorna lista de tickets do cliente."""
    resp = get_com_retry(s, f"{BASE}/admin/tickets.php",
                         params={"id_cliente": id_cliente})
    soup = BeautifulSoup(resp.text, "html.parser")
    tabela = soup.find("table")
    if not tabela:
        return []

    headers = [th.get_text(strip=True) for th in tabela.find_all("th")]
    tickets = []
    for tr in tabela.find_all("tr")[1:]:
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if not any(cells):
            continue
        row = dict(zip(headers, cells)) if headers else {}

        # Extrai id_financeiro e id_animal dos links da linha
        id_fin = id_ani = ""
        for a in tr.find_all("a", href=True):
            m1 = re.search(r"id_financeiro=(\d+)", a["href"])
            m2 = re.search(r"id_animal=(\d+)",    a["href"])
            if m1: id_fin = m1.group(1)
            if m2: id_ani = m2.group(1)

        row["id_cliente"]    = id_cliente
        row["id_financeiro"] = id_fin
        row["id_animal"]     = id_ani
        tickets.append(row)
    return tickets


def scrape_tickets(s):
    print("\n[2/2] Coletando histórico de tickets de cada cliente...")
    with open(os.path.join(config.OUTPUT_DIR, "clientes.csv"), encoding="utf-8-sig") as f:
        clientes = list(csv.DictReader(f))

    todos   = []
    colunas = None
    arquivo = None
    writer  = None

    for i, cliente in enumerate(clientes, 1):
        id_c = cliente["id_cliente"]
        if i % 50 == 0:
            print(f"  [{i}/{len(clientes)}] {cliente['nome']} — {len(todos)} tickets até agora")
        try:
            tickets = scrape_tickets_cliente(s, id_c)
            for t in tickets:
                if colunas is None:
                    # Ordena colunas: ids primeiro
                    base = ["id_cliente", "id_animal", "id_financeiro"]
                    colunas = base + [k for k in t if k not in base]
                    arquivo = open(TICKETS_OUT, "w", newline="", encoding="utf-8-sig")
                    writer  = csv.DictWriter(arquivo, fieldnames=colunas, extrasaction="ignore")
                    writer.writeheader()
                writer.writerow(t)
                arquivo.flush()
                todos.append(t)
        except Exception as e:
            print(f"    Erro em {cliente['nome']}: {e.__class__.__name__}")
        time.sleep(DELAY)

    if arquivo: arquivo.close()
    print(f"\n✓ {len(todos)} tickets salvos em {TICKETS_OUT}")


def main():
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    s = criar_sessao()
    if not login(s):
        return
    scrape_servicos(s)
    scrape_tickets(s)
    print("\n✓ Concluído!")


if __name__ == "__main__":
    main()