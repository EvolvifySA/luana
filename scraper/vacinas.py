"""
scraper/vacinas.py — Histórico de vacinas aplicadas por animal.
Gera vacinas.csv.   Uso:  python -m scraper.vacinas
"""

import config
from .client import NuvemVetClient, parse_tabela, salvar_csv, ler_csv


def main():
    nv = NuvemVetClient()
    if not nv.login():
        return
    animais = ler_csv("animais.csv")
    if not animais:
        print("✗ animais.csv não encontrado. Rode 'python -m scraper.clientes' antes.")
        return

    print(f"\nColetando vacinas de {len(animais)} animais...\n")
    todas = []
    ids = ["id_cliente", "id_animal", "nome_cliente", "nome_animal"]
    for i, a in enumerate(animais, 1):
        base = {k: a.get(k, "") for k in ids}
        if i % 50 == 0:
            print(f"  [{i}/{len(animais)}] {base['nome_cliente']}")
        try:
            soup = nv.get_soup("/admin/vacina_aplicada_animal.php",
                               params={"id_cliente": base["id_cliente"], "id_animal": base["id_animal"]})
            todas.extend(parse_tabela(soup, extra=base))
        except Exception as e:
            print(f"    ✗ {base['nome_animal']}: {e.__class__.__name__}")
        nv.sleep()

    salvar_csv("vacinas.csv", todas, ids)
    print(f"\n✓ {len(todas)} vacinas coletadas.")


if __name__ == "__main__":
    main()