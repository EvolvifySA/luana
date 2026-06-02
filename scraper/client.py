"""
scraper/client.py — Cliente HTTP compartilhado do NuvemVet.

Centraliza tudo que era duplicado em cada scraper:
  - criação de sessão
  - login
  - GET com retry automático
  - parse genérico de tabelas
  - utilitários de CSV

Uso:
    from scraper.client import NuvemVetClient
    nv = NuvemVetClient()
    nv.login()
    soup = nv.get_soup("/admin/listar_cliente.php", params={"limit": 500})
"""

import csv
import os
import time
from urllib.parse import urlparse, parse_qs
import requests
from bs4 import BeautifulSoup

import config


def extrair_param(href, param):
    """Extrai um parâmetro de query string de uma URL/href."""
    if not href:
        return None
    vals = parse_qs(urlparse(href).query).get(param)
    return vals[0] if vals else None

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0.0.0 Safari/537.36")


class NuvemVetClient:
    """Sessão autenticada com o NuvemVet e helpers de scraping."""

    def __init__(self, delay=None):
        self.base  = config.BASE_URL
        self.delay = config.DELAY if delay is None else delay
        self.s = requests.Session()
        self.s.headers["User-Agent"] = USER_AGENT

    # ─── Login ────────────────────────────────────────────────────────────────
    def login(self):
        print("Fazendo login...")
        resp = self.s.get(config.LOGIN_URL)
        soup = BeautifulSoup(resp.text, "html.parser")
        form = soup.find("form")
        data, action = {}, config.LOGIN_URL
        if form:
            for inp in form.find_all("input"):
                n = inp.get("name")
                if n:
                    data[n] = inp.get("value", "")
            act = form.get("action", "")
            if act:
                action = act if act.startswith("http") else "https://www.nuvemvet.com" + act

        for campo in ("email", "usuario", "login"):
            if campo in data:
                data[campo] = config.EMAIL
                break
        else:
            data["email"] = config.EMAIL
        for campo in ("senha", "password"):
            if campo in data:
                data[campo] = config.SENHA
                break
        else:
            data["senha"] = config.SENHA

        self.s.post(action, data=data, allow_redirects=True)
        ok = "dashboard" in self.s.get(f"{self.base}/admin/dashboard.php",
                                       allow_redirects=True).url
        print("✓ Login OK" if ok else "✗ Login falhou — verifique .env")
        return ok

    # ─── Requisições ──────────────────────────────────────────────────────────
    def get(self, path, tentativas=3, **kwargs):
        """GET com retry. `path` pode ser caminho /admin/... ou URL completa."""
        url = path if path.startswith("http") else f"{self.base}{path}"
        kwargs.setdefault("timeout", (10, 30))
        for i in range(tentativas):
            try:
                return self.s.get(url, **kwargs)
            except Exception as e:
                if i < tentativas - 1:
                    print(f"      Conexão caiu ({e.__class__.__name__}), tentando de novo...")
                    time.sleep(3)
                else:
                    raise
        return None

    def get_soup(self, path, **kwargs):
        resp = self.get(path, **kwargs)
        return BeautifulSoup(resp.text, "html.parser") if resp else None

    def sleep(self):
        time.sleep(self.delay)


# ─── Parsing ──────────────────────────────────────────────────────────────────

def parse_tabela(soup, extra=None):
    """
    Extrai a primeira tabela de um soup como lista de dicts.
    `extra` é um dict mesclado em cada linha (ex.: ids do animal).
    """
    if soup is None:
        return []
    tabela = soup.find("table")
    if not tabela:
        return []
    headers = [th.get_text(strip=True) for th in tabela.find_all("th")]
    registros = []
    for tr in tabela.find_all("tr")[1:]:
        celulas = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if not any(celulas):
            continue
        if headers:
            row = dict(zip(headers, celulas))
        else:
            row = {f"col_{i}": v for i, v in enumerate(celulas)}
        if extra:
            row = {**extra, **row}
        registros.append(row)
    return registros


# ─── CSV ──────────────────────────────────────────────────────────────────────

def caminho_dado(nome_arquivo):
    return os.path.join(config.OUTPUT_DIR, nome_arquivo)


def salvar_csv(nome_arquivo, dados, campos_primeiro=None):
    """Salva lista de dicts em CSV (UTF-8 BOM), ordenando colunas."""
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    if not dados:
        print(f"  (sem dados — {nome_arquivo})")
        return

    campos = list(campos_primeiro or [])
    vistos = set(campos)
    for row in dados:
        for c in row:
            if c not in vistos:
                campos.append(c)
                vistos.add(c)

    path = caminho_dado(nome_arquivo)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        w.writerows(dados)
    print(f"  → {path}  ({len(dados)} linhas)")


def ler_csv(nome_arquivo):
    path = caminho_dado(nome_arquivo)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))