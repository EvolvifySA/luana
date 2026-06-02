"""
scraper/cadastro_clientes.py — Dados cadastrais por cliente (CPF, contato, endereço).

Complementa clientes_completo.csv visitando o cadastro de cada cliente.
Gera clientes_cadastro.csv (salva linha a linha; resiste a interrupções).

Uso:  python -m scraper.cadastro_clientes
"""

import csv
import os
import config
from .client import NuvemVetClient, ler_csv, caminho_dado

CAMPOS_QUERO = {"cpf", "celular", "telefone", "email", "endereço", "endereco",
                "cidade", "estado", "bairro", "cep", "nascimento", "observação", "observacao"}
COLUNAS = ["id_cliente", "nome", "cpf", "celular", "telefone",
           "email", "endereço", "cidade", "cep", "nascimento", "observação"]


def extrair_pares(soup):
    dados = {}
    for tr in soup.find_all("tr"):
        cels = tr.find_all(["th", "td"])
        if len(cels) == 2:
            k = cels[0].get_text(strip=True).lower().rstrip(":")
            v = cels[1].get_text(strip=True)
            if v and any(c in k for c in CAMPOS_QUERO):
                dados[k] = v
    return dados


def get_cadastro(nv, id_cliente):
    for path in ("/admin/cadastro_cliente.php", "/admin/visualizar_perfil_completo_cliente.php",
                 "/admin/editar_cliente.php"):
        try:
            soup = nv.get_soup(path, params={"id_cliente": id_cliente})
            if soup:
                dados = extrair_pares(soup)
                if dados:
                    return dados
        except Exception:
            continue
    return {}


def main():
    nv = NuvemVetClient(delay=0.5)
    if not nv.login():
        return
    clientes = ler_csv("clientes.csv")
    if not clientes:
        print("✗ clientes.csv não encontrado. Rode 'python -m scraper.clientes' antes.")
        return

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    saida = caminho_dado("clientes_cadastro.csv")
    print(f"\n{len(clientes)} clientes...\n")
    with open(saida, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS, extrasaction="ignore")
        w.writeheader()
        for i, cli in enumerate(clientes, 1):
            if i % 50 == 0:
                print(f"  [{i}/{len(clientes)}] {cli['nome']}")
            dados = get_cadastro(nv, cli["id_cliente"])
            dados.update({"id_cliente": cli["id_cliente"], "nome": cli["nome"]})
            w.writerow(dados)
            f.flush()
            nv.sleep()
    print(f"\n✓ Salvo em {saida}")


if __name__ == "__main__":
    main()