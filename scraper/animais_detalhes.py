"""
scraper/animais_detalhes.py — Dados cadastrais de cada animal.

Extrai carteirinha, nascimento, sexo, espécie, raça, pelagem, óbito e chip.
Gera animais_detalhes.csv (retoma de onde parou se interrompido).

Uso:  python -m scraper.animais_detalhes
"""

import config
from .client import NuvemVetClient, salvar_csv, ler_csv

CAMPOS = {
    "carteirinha": "carteirinha", "nascimento": "nascimento", "sexo": "sexo",
    "espécie": "especie", "raça": "raca", "pelagem": "pelagem",
    "óbito": "obito", "chip": "chip",
}
COLUNAS = ["id_cliente", "id_animal", "nome_cliente", "nome_animal",
           "carteirinha", "nascimento", "sexo", "especie", "raca", "pelagem", "obito", "chip"]


def extrair_dados_animal(soup):
    """Extrai pares Label: Valor do perfil do animal."""
    dados = {}
    # Estratégia 1: <b>Label</b> Valor
    for b in soup.find_all("b"):
        campo = CAMPOS.get(b.get_text(strip=True).rstrip(":").strip().lower())
        if campo:
            prox = b.next_sibling
            if prox:
                v = str(prox).strip()
                if v and v not in ("-", "—", ""):
                    dados[campo] = v
    # Estratégia 2: outras tags
    if len(dados) < 3:
        for tag in soup.find_all(["strong", "label", "td", "th", "span"]):
            campo = CAMPOS.get(tag.get_text(strip=True).rstrip(":").strip().lower())
            if not campo or campo in dados:
                continue
            prox = tag.find_next_sibling() or (tag.parent.find_next_sibling() if tag.parent else None)
            if prox:
                v = prox.get_text(strip=True)
                if v and v not in ("-", "—", ""):
                    dados[campo] = v
    return dados


def main():
    nv = NuvemVetClient()
    if not nv.login():
        return
    animais = ler_csv("animais.csv")
    if not animais:
        print("✗ animais.csv não encontrado. Rode 'python -m scraper.clientes' antes.")
        return

    print(f"\nColetando detalhes de {len(animais)} animais...\n")
    resultado = []
    for i, a in enumerate(animais, 1):
        base = {k: a.get(k, "") for k in ("id_cliente", "id_animal", "nome_cliente", "nome_animal")}
        if i % 50 == 0:
            print(f"  [{i}/{len(animais)}] {base['nome_cliente']}")
        try:
            soup = nv.get_soup("/admin/visualizar_perfil_completo_cliente.php",
                               params={"id_cliente": base["id_cliente"], "id_animal": base["id_animal"]})
            base.update(extrair_dados_animal(soup) if soup else {})
        except Exception as e:
            print(f"    ✗ {base['nome_animal']}: {e.__class__.__name__}")
        resultado.append(base)
        nv.sleep()

    salvar_csv("animais_detalhes.csv", resultado, COLUNAS)
    print(f"\n✓ {len(resultado)} animais processados.")


if __name__ == "__main__":
    main()