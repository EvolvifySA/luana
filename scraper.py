#!/usr/bin/env python3
"""
NuvemVet Scraper - Extração de dados para migração
Extrai: clientes, animais, consultas, vacinas, receituário,
        exames, cirurgias, pesagens, anotações, retorno de vacinas
"""

import requests
from bs4 import BeautifulSoup
import csv
import time
import os
import re
from urllib.parse import urlparse, parse_qs

import config

BASE  = config.BASE_URL
DELAY = config.DELAY


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

    # Preenche credenciais — tenta os campos mais comuns
    for campo_email in ["email", "usuario", "login", "user"]:
        if campo_email in data:
            data[campo_email] = config.EMAIL
            break
    else:
        data["email"] = config.EMAIL

    for campo_senha in ["senha", "password", "pass"]:
        if campo_senha in data:
            data[campo_senha] = config.SENHA
            break
    else:
        data["senha"] = config.SENHA

    resp = s.post(action, data=data, allow_redirects=True)

    # Verifica se entrou no painel
    check = s.get(f"{BASE}/admin/dashboard.php", allow_redirects=True)
    if "dashboard" in check.url and "entrar" not in check.url:
        print("✓ Login OK")
        return True

    print(f"✗ Login falhou — URL final: {check.url}")
    print("  Verifique EMAIL e SENHA em config.py")
    return False


# ─── UTILITÁRIOS ──────────────────────────────────────────────────────────────

def extrair_param(href, param):
    if not href:
        return None
    qs = parse_qs(urlparse(href).query)
    vals = qs.get(param)
    return vals[0] if vals else None


def parse_tabela(soup):
    """Extrai todas as tabelas de uma página como lista de dicts."""
    registros = []
    for tabela in soup.find_all("table"):
        headers = [th.get_text(strip=True) for th in tabela.find_all("th")]
        for tr in tabela.find_all("tr")[1:]:
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if not any(c.strip() for c in cells):
                continue
            if headers:
                row = dict(zip(headers, cells))
            else:
                row = {"col_" + str(i): v for i, v in enumerate(cells)}
            registros.append(row)
    return registros


def salvar_csv(nome_arquivo, dados, campos_primeiro=None):
    if not dados:
        print(f"  (sem dados — {nome_arquivo})")
        return

    # Coleta todos os campos mantendo ordem
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


# ─── CLIENTES ─────────────────────────────────────────────────────────────────

def listar_clientes(s):
    """
    Percorre todas as páginas de listar_cliente.php.
    Retorna lista de dicts com id_cliente, nome e lista de animais.
    """
    print("\n[1/4] Listando clientes e animais...")
    clientes = {}
    pagina   = 1

    while True:
        resp = s.get(
            f"{BASE}/admin/listar_cliente.php",
            params={"limit": config.LIMIT, "p": pagina},
        )
        soup = BeautifulSoup(resp.text, "html.parser")

        tabela = soup.find("table")
        if not tabela:
            break

        linhas = tabela.find_all("tr")[1:]
        if not linhas:
            break

        novos = 0
        for linha in linhas:
            cels = linha.find_all("td")
            if len(cels) < 3:
                continue

            # Nome do cliente
            nome = (cels[0].find("button") or cels[0]).get_text(strip=True)

            # id_cliente: extraído do link da lupa (coluna Atendimento)
            lupa = linha.find("a", href=lambda h: h and "id_cliente=" in str(h))
            if not lupa:
                continue
            id_cliente = extrair_param(lupa["href"], "id_cliente")
            if not id_cliente:
                continue

            if id_cliente not in clientes:
                clientes[id_cliente] = {
                    "id_cliente": id_cliente,
                    "nome":       nome,
                    "animais":    [],
                }
                novos += 1

            # Animais: links com id_animal na coluna Animais
            col_animais = cels[2]
            ids_ja = {a["id_animal"] for a in clientes[id_cliente]["animais"]}
            for a_tag in col_animais.find_all("a", href=True):
                id_animal = extrair_param(a_tag["href"], "id_animal")
                if id_animal and id_animal not in ids_ja:
                    clientes[id_cliente]["animais"].append({
                        "id_animal":  id_animal,
                        "nome_animal": a_tag.get_text(strip=True),
                    })
                    ids_ja.add(id_animal)

        print(f"  Página {pagina}: {novos} novos clientes")

        # Próxima página
        prox = soup.find("a", string=re.compile(r"[Pp]r[oó]xim|Next|>>"))
        if not prox or novos == 0:
            break
        pagina += 1
        time.sleep(DELAY)

    total = len(clientes)
    print(f"  Total: {total} clientes")
    return list(clientes.values())


def exportar_relatorio_clientes(s):
    """
    Acessa o relatório de clientes cadastrados.
    Tenta baixar o CSV direto (botão 'Exportar Lista em CSV').
    Caso não funcione, faz parse do HTML.
    """
    print("\n[2/4] Relatório de clientes cadastrados (CPF, endereço, celular)...")
    url    = f"{BASE}/admin/relatorio_clientes_cadastrados.php"
    params = {
        "page":        "relatorio_clientes_lista",
        "data_inicio": "01/01/2000",
        "data_final":  "31/12/2099",
    }
    resp = s.get(url, params=params)
    soup = BeautifulSoup(resp.text, "html.parser")

    # Tenta exportar CSV via botão
    btn = (
        soup.find("a",      string=re.compile(r"CSV", re.I)) or
        soup.find("button", string=re.compile(r"CSV", re.I)) or
        soup.find("a",      href=re.compile(r"csv|export", re.I))
    )
    if btn:
        href = btn.get("href") or btn.get("onclick", "")
        if href and not href.startswith("javascript"):
            csv_url  = href if href.startswith("http") else BASE + "/" + href.lstrip("/")
            csv_resp = s.get(csv_url)
            ct       = csv_resp.headers.get("Content-Type", "")
            if "csv" in ct or "octet" in ct or csv_resp.text.strip().startswith(("#", "\"", "N", "C")):
                path = os.path.join(config.OUTPUT_DIR, "clientes_completo_raw.csv")
                with open(path, "wb") as f:
                    f.write(csv_resp.content)
                print(f"  → CSV baixado diretamente: {path}")
                return []

    # Fallback: parse da tabela HTML
    dados = parse_tabela(soup)
    print(f"  {len(dados)} registros (parse HTML)")
    return dados


# ─── PERFIL DO ANIMAL ─────────────────────────────────────────────────────────

SECOES = {
    "consultas":   "consulta_animal.php",
    "vacinas":     "vacina_animal.php",
    "receituario": "receituario_animal.php",
    "exames":      "exame_animal_pdo.php",
    "cirurgias":   "cirurgia_animal.php",
    "pesagens":    "pesagem_animal.php",
    "anotacoes":   "anotacao_animal.php",
}


def get_secao_animal(s, php, id_cliente, id_animal):
    resp = s.get(
        f"{BASE}/admin/{php}",
        params={"id_cliente": id_cliente, "id_animal": id_animal},
    )
    soup = BeautifulSoup(resp.text, "html.parser")
    return parse_tabela(soup)


# ─── RELATÓRIO RETORNO DE VACINAS ─────────────────────────────────────────────

def get_retorno_vacinas(s):
    print("\n[4/4] Relatório de retorno de vacinas...")
    resp = s.get(
        f"{BASE}/admin/relatorios_vacinas_retorno.php",
        params={
            "data_inicio":        "01/01/2000",
            "data_final":         "31/12/2099",
            "nome_proprietario":  "",
            "nome_animal":        "",
            "veterinario":        "-1",
            "lido_retorno":       "-1",
            "avisado_pelo_whats": "-1",
            "aplicada_retorno":   "-1",
        },
    )
    soup    = BeautifulSoup(resp.text, "html.parser")
    dados   = parse_tabela(soup)
    print(f"  {len(dados)} registros")
    return dados


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    s = criar_sessao()
    if not login(s):
        return

    # 1. Lista de clientes + animais
    clientes = listar_clientes(s)

    # Salva lista básica
    salvar_csv(
        "clientes.csv",
        [{"id_cliente": c["id_cliente"], "nome": c["nome"]} for c in clientes],
        ["id_cliente", "nome"],
    )

    # 2. Relatório com dados completos (CPF, endereço, celular)
    rel = exportar_relatorio_clientes(s)
    if rel:
        salvar_csv("clientes_completo.csv", rel)

    # 3. Dados por animal
    print("\n[3/4] Extraindo histórico de cada animal...")
    todos_animais  = []
    secoes_dados   = {k: [] for k in SECOES}
    total_clientes = len(clientes)

    for i, cliente in enumerate(clientes, 1):
        id_c   = cliente["id_cliente"]
        nome_c = cliente["nome"]
        print(f"  [{i}/{total_clientes}] {nome_c}")

        for animal in cliente["animais"]:
            id_a   = animal["id_animal"]
            nome_a = animal["nome_animal"]

            todos_animais.append({
                "id_cliente":   id_c,
                "id_animal":    id_a,
                "nome_cliente": nome_c,
                "nome_animal":  nome_a,
            })

            for nome_sec, php in SECOES.items():
                try:
                    dados = get_secao_animal(s, php, id_c, id_a)
                    for d in dados:
                        d["id_cliente"]   = id_c
                        d["id_animal"]    = id_a
                        d["nome_cliente"] = nome_c
                        d["nome_animal"]  = nome_a
                    secoes_dados[nome_sec].extend(dados)
                except Exception as e:
                    print(f"    ✗ {nome_sec} ({nome_a}): {e}")
                time.sleep(DELAY)

    salvar_csv(
        "animais.csv",
        todos_animais,
        ["id_cliente", "id_animal", "nome_cliente", "nome_animal"],
    )
    for nome_sec, dados in secoes_dados.items():
        salvar_csv(
            f"{nome_sec}.csv",
            dados,
            ["id_cliente", "id_animal", "nome_cliente", "nome_animal"],
        )

    # 4. Retorno de vacinas
    retorno = get_retorno_vacinas(s)
    salvar_csv("retorno_vacinas.csv", retorno)

    print(f"\n✓ Exportação concluída! Arquivos em: {config.OUTPUT_DIR}/")
    print("  Arquivos gerados:")
    for f in sorted(os.listdir(config.OUTPUT_DIR)):
        path = os.path.join(config.OUTPUT_DIR, f)
        print(f"    {f}  ({os.path.getsize(path):,} bytes)")


if __name__ == "__main__":
    main()
