#!/usr/bin/env python3
"""
puxar_vacinas.py — Coleta histórico de vacinas de cada animal.
URL confirmada: vacina_aplicada_animal.php?id_cliente=X&id_animal=Y
Salva em: dados_exportados/vacinas.csv
"""

import requests
from bs4 import BeautifulSoup
import csv, time, os
import config

BASE  = config.BASE_URL
DELAY = 0.5
OUTPUT = os.path.join(config.OUTPUT_DIR, "vacinas.csv")


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
        try:
            return s.get(url, **kwargs)
        except Exception as e:
            if i < 2: time.sleep(3)
            else: raise


def ja_coletados():
    if not os.path.exists(OUTPUT): return set()
    with open(OUTPUT, encoding="utf-8-sig") as f:
        return {(r["id_cliente"], r["id_animal"]) for r in csv.DictReader(f)}


def main():
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    s = criar_sessao()
    if not login(s): return

    with open(os.path.join(config.OUTPUT_DIR, "animais.csv"), encoding="utf-8-sig") as f:
        animais = list(csv.DictReader(f))

    ja_feitos = ja_coletados()
    pendentes = [a for a in animais if (a["id_cliente"], a["id_animal"]) not in ja_feitos]
    print(f"\n{len(animais)} animais | {len(ja_feitos)} já coletados | {len(pendentes)} pendentes\n")

    modo = "a" if ja_feitos else "w"
    colunas_base = ["id_cliente", "id_animal", "nome_cliente", "nome_animal"]
    colunas_todas = None
    arquivo = None
    writer  = None
    total_registros = 0

    for i, animal in enumerate(pendentes, 1):
        id_c, id_a = animal["id_cliente"], animal["id_animal"]
        print(f"  [{i}/{len(pendentes)}] {animal['nome_cliente']} → {animal['nome_animal']}")

        try:
            resp = get_com_retry(s, f"{BASE}/admin/vacina_aplicada_animal.php",
                                 params={"id_cliente": id_c, "id_animal": id_a})
            soup = BeautifulSoup(resp.text, "html.parser")
            tabela = soup.find("table")
            if not tabela:
                time.sleep(DELAY)
                continue

            headers = [th.get_text(strip=True) for th in tabela.find_all("th")]
            rows    = tabela.find_all("tr")[1:]

            for tr in rows:
                cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
                if not any(cells): continue

                row = {"id_cliente": id_c, "id_animal": id_a,
                       "nome_cliente": animal["nome_cliente"],
                       "nome_animal":  animal["nome_animal"]}
                if headers:
                    row.update(dict(zip(headers, cells)))
                else:
                    row.update({"col_"+str(i): v for i, v in enumerate(cells)})

                # Abre arquivo na primeira linha encontrada
                if colunas_todas is None:
                    colunas_todas = colunas_base + [k for k in row if k not in colunas_base]
                    arquivo = open(OUTPUT, modo, newline="", encoding="utf-8-sig")
                    writer  = csv.DictWriter(arquivo, fieldnames=colunas_todas, extrasaction="ignore")
                    if modo == "w" or not ja_feitos:
                        writer.writeheader()

                writer.writerow(row)
                arquivo.flush()
                total_registros += 1

        except Exception as e:
            print(f"    Erro: {e.__class__.__name__}")

        time.sleep(DELAY)

    if arquivo: arquivo.close()
    print(f"\n✓ Concluído! {total_registros} vacinas salvas em {OUTPUT}")


if __name__ == "__main__":
    main()
