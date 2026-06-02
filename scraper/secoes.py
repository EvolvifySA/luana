"""
scraper/secoes.py — Seções que faltaram no scraper principal.

Descobre automaticamente a URL de cada seção (testando candidatas) e coleta:
receituario, anotacoes, vermifugos, cirurgias, agendamentos.
Gera um CSV por seção (pula as que já existem).

Uso:  python -m scraper.secoes
"""

import os
import config
from .client import NuvemVetClient, parse_tabela, salvar_csv, ler_csv, caminho_dado

SECOES_URLS = {
    "receituario": ["receituario_animal.php", "receita_animal.php", "receituarios_animal.php"],
    "anotacoes":   ["anotacao_animal.php", "anotacoes_animal.php", "nota_animal.php"],
    "vermifugos":  ["vermifugo_animal.php", "vermifugos_animal.php",
                    "antipulga_animal.php", "vermifugo_antipulga_animal.php"],
    "cirurgias":   ["cirurgia_animal.php"],
    "agendamentos": ["agendamentos_animal.php", "agendamento_animal.php"],
}


def descobrir_url(nv, php_list, id_c, id_a):
    for php in php_list:
        try:
            soup = nv.get_soup(f"/admin/{php}", params={"id_cliente": id_c, "id_animal": id_a})
            if soup and (soup.find("table") or
                         soup.find(string=lambda t: t and "nenhum" in t.lower())):
                print(f"    ✓ URL: {php}")
                return php
        except Exception:
            continue
    return None


def main():
    nv = NuvemVetClient()
    if not nv.login():
        return
    animais = ler_csv("animais.csv")
    if not animais:
        print("✗ animais.csv não encontrado. Rode 'python -m scraper.clientes' antes.")
        return

    teste = animais[min(5, len(animais) - 1)]
    id_c, id_a = teste["id_cliente"], teste["id_animal"]
    print(f"\nDescoberta de URLs com: {teste['nome_cliente']} → {teste['nome_animal']}\n")

    confirmadas = {}
    for secao, urls in SECOES_URLS.items():
        if os.path.exists(caminho_dado(f"{secao}.csv")):
            print(f"  {secao}: já existe, pulando")
            continue
        print(f"  Testando '{secao}'...")
        php = descobrir_url(nv, urls, id_c, id_a)
        if php:
            confirmadas[secao] = php
        else:
            print(f"    ✗ nenhuma URL funcionou para '{secao}'")

    ids = ["id_cliente", "id_animal", "nome_cliente", "nome_animal"]
    for secao, php in confirmadas.items():
        print(f"\nColetando '{secao}' ({php})...")
        dados = []
        for i, a in enumerate(animais, 1):
            base = {k: a.get(k, "") for k in ids}
            if i % 100 == 0:
                print(f"  [{i}/{len(animais)}]")
            try:
                soup = nv.get_soup(f"/admin/{php}",
                                   params={"id_cliente": base["id_cliente"], "id_animal": base["id_animal"]})
                dados.extend(parse_tabela(soup, extra=base))
            except Exception:
                pass
            nv.sleep()
        salvar_csv(f"{secao}.csv", dados, ids)

    print("\n✓ Concluído!")


if __name__ == "__main__":
    main()