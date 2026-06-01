#!/usr/bin/env python3
"""
puxar_animais_detalhes.py — Coleta dados cadastrais de cada animal.

Lê animais.csv (já existente) e para cada animal visita a página de perfil
no NuvemVet para extrair: carteirinha, nascimento, sexo, espécie, raça,
pelagem, óbito e chip.

Salva em: dados_exportados/animais_detalhes.csv
Não altera nenhum arquivo existente.

Rode: python puxar_animais_detalhes.py
"""

import requests
from bs4 import BeautifulSoup
import csv
import time
import os

import config

BASE  = config.BASE_URL
DELAY = 0.5

CAMPOS = {
    "Carteirinha": "carteirinha",
    "Nascimento":  "nascimento",
    "Sexo":        "sexo",
    "Espécie":     "especie",
    "Raça":        "raca",
    "Pelagem":     "pelagem",
    "Óbito":       "obito",
    "Chip":        "chip",
}

COLUNAS_SAIDA = [
    "id_cliente", "id_animal", "nome_cliente", "nome_animal",
    "carteirinha", "nascimento", "sexo", "especie",
    "raca", "pelagem", "obito", "chip",
]

OUTPUT = os.path.join(config.OUTPUT_DIR, "animais_detalhes.csv")


# ─── LOGIN ────────────────────────────────────────────────────────────────────

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
            data[campo] = config.EMAIL
            break
    else:
        data["email"] = config.EMAIL
    for campo in ["senha", "password"]:
        if campo in data:
            data[campo] = config.SENHA
            break
    else:
        data["senha"] = config.SENHA
    s.post(action, data=data, allow_redirects=True)
    check = s.get(f"{BASE}/admin/dashboard.php", allow_redirects=True)
    if "dashboard" in check.url:
        print("✓ Login OK")
        return True
    print("✗ Login falhou")
    return False


# ─── EXTRAÇÃO ────────────────────────────────────────────────────────────────

def extrair_dados_animal(soup):
    """Extrai pares Label: Valor do perfil do animal."""
    dados = {}
    campos_lower = {k.lower(): v for k, v in CAMPOS.items()}

    # Estratégia 1: tags <b> seguidas de texto
    for b_tag in soup.find_all("b"):
        label = b_tag.get_text(strip=True).rstrip(":").strip().lower()
        campo = campos_lower.get(label)
        if not campo:
            continue
        # Valor é o texto imediatamente após o <b>
        proximo = b_tag.next_sibling
        if proximo:
            valor = str(proximo).strip()
            if valor and valor not in ("-", "—", ""):
                dados[campo] = valor

    # Estratégia 2: <strong> ou <label> com texto parecido
    if len(dados) < 3:
        for tag in soup.find_all(["strong", "label", "td", "th", "span"]):
            label = tag.get_text(strip=True).rstrip(":").strip().lower()
            campo = campos_lower.get(label)
            if not campo or campo in dados:
                continue
            proximo = tag.find_next_sibling() or tag.parent.find_next_sibling()
            if proximo:
                valor = proximo.get_text(strip=True)
                if valor and valor not in ("-", "—", ""):
                    dados[campo] = valor

    return dados


def get_animal_detalhes(s, id_cliente, id_animal):
    """Tenta buscar dados do animal em diferentes URLs."""
    urls = [
        f"{BASE}/admin/visualizar_perfil_completo_cliente.php"
        f"?id_cliente={id_cliente}&id_animal={id_animal}",

        f"{BASE}/admin/visualizar_perfil_completo_cliente.php"
        f"?id_cliente={id_cliente}",
    ]

    for url in urls:
        try:
            resp = s.get(url, timeout=(10, 30))
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            dados = extrair_dados_animal(soup)
            if dados:
                return dados
        except Exception as e:
            print(f"    Erro ao acessar {url}: {e.__class__.__name__}")
            continue
    return {}


# ─── MAIN ────────────────────────────────────────────────────────────────────

def ler_animais():
    path = os.path.join(config.OUTPUT_DIR, "animais.csv")
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def ja_coletados():
    """Retorna set de (id_cliente, id_animal) já presentes no CSV de saída."""
    if not os.path.exists(OUTPUT):
        return set()
    with open(OUTPUT, encoding="utf-8-sig") as f:
        return {(r["id_cliente"], r["id_animal"]) for r in csv.DictReader(f)}


def main():
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    s = criar_sessao()
    if not login(s):
        return

    animais     = ler_animais()
    ja_feitos   = ja_coletados()
    pendentes   = [a for a in animais
                   if (a["id_cliente"], a["id_animal"]) not in ja_feitos]

    print(f"\n{len(animais)} animais no total")
    print(f"{len(ja_feitos)} já coletados anteriormente")
    print(f"{len(pendentes)} a processar\n")

    # Abre CSV em modo append (preserva o que já tem)
    modo    = "a" if ja_feitos else "w"
    arquivo = open(OUTPUT, modo, newline="", encoding="utf-8-sig")
    writer  = csv.DictWriter(arquivo, fieldnames=COLUNAS_SAIDA, extrasaction="ignore")
    if not ja_feitos:
        writer.writeheader()

    coletados = 0
    sem_dados = 0

    for i, animal in enumerate(pendentes, 1):
        id_c   = animal["id_cliente"]
        id_a   = animal["id_animal"]
        nome_c = animal["nome_cliente"]
        nome_a = animal["nome_animal"]

        print(f"  [{i}/{len(pendentes)}] {nome_c} → {nome_a}")

        detalhes = get_animal_detalhes(s, id_c, id_a)

        row = {
            "id_cliente":  id_c,
            "id_animal":   id_a,
            "nome_cliente": nome_c,
            "nome_animal": nome_a,
        }
        row.update(detalhes)

        writer.writerow(row)
        arquivo.flush()

        if detalhes:
            campos_encontrados = list(detalhes.keys())
            print(f"    ✓ {', '.join(campos_encontrados)}")
            coletados += 1
        else:
            print(f"    (sem dados estruturados)")
            sem_dados += 1

        time.sleep(DELAY)

    arquivo.close()

    print(f"\n✓ Concluído!")
    print(f"  Com dados:   {coletados}")
    print(f"  Sem dados:   {sem_dados}")
    print(f"  Salvo em:    {OUTPUT}")


if __name__ == "__main__":
    main()
