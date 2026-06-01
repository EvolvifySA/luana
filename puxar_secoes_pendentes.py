#!/usr/bin/env python3
"""
puxar_secoes_pendentes.py — Coleta as seções que faltaram no scraper original.

Testa automaticamente os possíveis nomes de URL para cada seção e salva
apenas o que encontrar dados. Gera um CSV por seção.

Seções alvo: receituario, anotacoes, vermifugos, cirurgias, agendamentos
"""

import requests
from bs4 import BeautifulSoup
import csv, time, os, json
import config

BASE  = config.BASE_URL
DELAY = 0.5

# URLs candidatas por seção (em ordem de prioridade)
SECOES_URLS = {
    "receituario": [
        "receituario_animal.php",
        "receita_animal.php",
        "receituarios_animal.php",
    ],
    "anotacoes": [
        "anotacao_animal.php",
        "anotacoes_animal.php",
        "nota_animal.php",
    ],
    "vermifugos": [
        "vermifugo_animal.php",
        "vermifugos_animal.php",
        "antipulga_animal.php",
        "vermifugo_antipulga_animal.php",
    ],
    "cirurgias": [
        "cirurgia_animal.php",
    ],
    "agendamentos": [
        "agendamentos_animal.php",
        "agendamento_animal.php",
    ],
}


def criar_sessao():
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    return s


def login(s):
    print("Fazendo login...")
    resp = s.get(config.LOGIN_URL)
    soup = BeautifulSoup(resp.text, "html.parser")
    form = soup.find("form")
    data, action = {}, config.LOGIN_URL
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
    check = s.get(f"{BASE}/admin/dashboard.php", allow_redirects=True)
    ok = "dashboard" in check.url
    print("✓ Login OK" if ok else "✗ Login falhou")
    return ok


def get_com_retry(s, url, **kwargs):
    kwargs.setdefault("timeout", (10, 30))
    for i in range(3):
        try: return s.get(url, **kwargs)
        except Exception as e:
            if i < 2: time.sleep(2)
            else: raise


def descobrir_url(s, nome_secao, id_cliente_teste, id_animal_teste):
    """Testa as URLs candidatas e retorna qual funciona."""
    for php in SECOES_URLS[nome_secao]:
        try:
            resp = get_com_retry(s, f"{BASE}/admin/{php}",
                                 params={"id_cliente": id_cliente_teste,
                                         "id_animal":  id_animal_teste})
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            # Considera válida se a página tem uma tabela OU tem conteúdo específico
            if soup.find("table") or soup.find(string=lambda t: t and "nenhum" in t.lower()):
                print(f"    ✓ URL encontrada: {php}")
                return php
        except Exception:
            continue
    return None


def scrape_secao(s, php, id_cliente, id_animal):
    """Raspa uma seção e retorna lista de dicts."""
    try:
        resp = get_com_retry(s, f"{BASE}/admin/{php}",
                             params={"id_cliente": id_cliente, "id_animal": id_animal})
        soup = BeautifulSoup(resp.text, "html.parser")
        tabela = soup.find("table")
        if not tabela: return []
        headers = [th.get_text(strip=True) for th in tabela.find_all("th")]
        rows = []
        for tr in tabela.find_all("tr")[1:]:
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if not any(cells): continue
            row = dict(zip(headers, cells)) if headers else {"col_"+str(i): v for i,v in enumerate(cells)}
            rows.append(row)
        return rows
    except Exception:
        return []


def main():
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    s = criar_sessao()
    if not login(s): return

    with open(os.path.join(config.OUTPUT_DIR, "animais.csv"), encoding="utf-8-sig") as f:
        animais = list(csv.DictReader(f))

    # Usa o primeiro animal com dados para descobrir URLs
    animal_teste = animais[5]  # pega um do meio para ter mais chance de ter dados
    id_c_teste = animal_teste["id_cliente"]
    id_a_teste = animal_teste["id_animal"]

    print(f"\nDescoberta de URLs usando: {animal_teste['nome_cliente']} → {animal_teste['nome_animal']}")
    print("="*60)

    urls_confirmadas = {}
    for secao in SECOES_URLS:
        # Pula se o CSV já existe
        csv_path = os.path.join(config.OUTPUT_DIR, f"{secao}.csv")
        if os.path.exists(csv_path):
            print(f"  {secao}: JÁ EXISTE ({csv_path}), pulando")
            continue
        print(f"  Testando URLs para '{secao}'...")
        php = descobrir_url(s, secao, id_c_teste, id_a_teste)
        if php:
            urls_confirmadas[secao] = php
        else:
            print(f"    ✗ Nenhuma URL funcionou para '{secao}'")
        time.sleep(0.5)

    if not urls_confirmadas:
        print("\nNenhuma URL nova descoberta.")
        return

    print(f"\nURLs confirmadas: {json.dumps(urls_confirmadas, indent=2)}")
    print("\nIniciando coleta...\n")

    # Coleta para cada seção confirmada
    for secao, php in urls_confirmadas.items():
        csv_path = os.path.join(config.OUTPUT_DIR, f"{secao}.csv")
        print(f"\n{'='*50}")
        print(f"Coletando: {secao} ({php})")
        print(f"{'='*50}")

        colunas_base = ["id_cliente", "id_animal", "nome_cliente", "nome_animal"]
        colunas_todas = None
        arquivo = None
        writer  = None
        total   = 0

        for i, animal in enumerate(animais, 1):
            id_c = animal["id_cliente"]
            id_a = animal["id_animal"]

            if i % 50 == 0:
                print(f"  [{i}/{len(animais)}] {animal['nome_cliente']}")

            rows = scrape_secao(s, php, id_c, id_a)
            for row in rows:
                full_row = {"id_cliente": id_c, "id_animal": id_a,
                            "nome_cliente": animal["nome_cliente"],
                            "nome_animal":  animal["nome_animal"],
                            **row}
                if colunas_todas is None:
                    colunas_todas = colunas_base + [k for k in full_row if k not in colunas_base]
                    arquivo = open(csv_path, "w", newline="", encoding="utf-8-sig")
                    writer  = csv.DictWriter(arquivo, fieldnames=colunas_todas, extrasaction="ignore")
                    writer.writeheader()
                writer.writerow(full_row)
                arquivo.flush()
                total += 1

            time.sleep(DELAY)

        if arquivo: arquivo.close()
        if total > 0:
            print(f"  ✓ {total} registros salvos em {csv_path}")
        else:
            print(f"  (sem dados encontrados para {secao})")

    print("\n✓ Coleta concluída!")


if __name__ == "__main__":
    main()
