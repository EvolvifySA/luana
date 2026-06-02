"""
scraper/clientes.py — Coleta clientes, animais e histórico completo.

Gera:
  clientes.csv          (id_cliente, nome)
  animais.csv           (id_cliente, id_animal, nome_cliente, nome_animal)
  clientes_completo.csv (relatório com CPF, endereço, celular)
  consultas/vacinas/receituario/exames/cirurgias/pesagens/anotacoes.csv
  retorno_vacinas.csv

Uso:  python -m scraper.clientes
"""

import re
import config
from .client import NuvemVetClient, parse_tabela, salvar_csv, extrair_param

# Seções coletadas por animal (nome -> endpoint)
SECOES = {
    "consultas":   "consulta_animal.php",
    "vacinas":     "vacina_aplicada_animal.php",
    "receituario": "receituario_animal.php",
    "exames":      "exame_animal_pdo.php",
    "cirurgias":   "cirurgia_animal.php",
    "pesagens":    "pesagem_animal.php",
    "anotacoes":   "anotacao_animal.php",
}


def listar_clientes(nv):
    """Percorre todas as páginas de listar_cliente.php."""
    print("\n[1/4] Listando clientes e animais...")
    clientes, pagina = {}, 1
    while True:
        soup = nv.get_soup("/admin/listar_cliente.php",
                           params={"limit": config.LIMIT, "p": pagina})
        tabela = soup.find("table") if soup else None
        linhas = tabela.find_all("tr")[1:] if tabela else []
        if not linhas:
            break

        novos = 0
        for linha in linhas:
            cels = linha.find_all("td")
            if len(cels) < 3:
                continue
            nome = (cels[0].find("button") or cels[0]).get_text(strip=True)
            lupa = linha.find("a", href=lambda h: h and "id_cliente=" in str(h))
            if not lupa:
                continue
            id_cliente = extrair_param(lupa["href"], "id_cliente")
            if not id_cliente:
                continue
            if id_cliente not in clientes:
                clientes[id_cliente] = {"id_cliente": id_cliente, "nome": nome, "animais": []}
                novos += 1
            ids_ja = {a["id_animal"] for a in clientes[id_cliente]["animais"]}
            for a_tag in cels[2].find_all("a", href=True):
                id_animal = extrair_param(a_tag["href"], "id_animal")
                if id_animal and id_animal not in ids_ja:
                    clientes[id_cliente]["animais"].append(
                        {"id_animal": id_animal, "nome_animal": a_tag.get_text(strip=True)})
                    ids_ja.add(id_animal)

        print(f"  Página {pagina}: {novos} novos clientes")
        prox = soup.find("a", string=re.compile(r"[Pp]r[oó]xim|Next|>>"))
        if not prox or novos == 0:
            break
        pagina += 1
        nv.sleep()

    print(f"  Total: {len(clientes)} clientes")
    return list(clientes.values())


def relatorio_clientes(nv):
    """Relatório de clientes cadastrados (CPF, endereço, celular)."""
    print("\n[2/4] Relatório de clientes cadastrados...")
    soup = nv.get_soup("/admin/relatorio_clientes_cadastrados.php",
                       params={"page": "relatorio_clientes_lista",
                               "data_inicio": "01/01/2000", "data_final": "31/12/2099"})
    dados = parse_tabela(soup)
    print(f"  {len(dados)} registros")
    return dados


def retorno_vacinas(nv):
    print("\n[4/4] Relatório de retorno de vacinas...")
    soup = nv.get_soup("/admin/relatorios_vacinas_retorno.php",
                       params={"data_inicio": "01/01/2000", "data_final": "31/12/2099",
                               "nome_proprietario": "", "nome_animal": "",
                               "veterinario": "-1", "lido_retorno": "-1",
                               "avisado_pelo_whats": "-1", "aplicada_retorno": "-1"})
    dados = parse_tabela(soup)
    print(f"  {len(dados)} registros")
    return dados


def main():
    nv = NuvemVetClient()
    if not nv.login():
        return

    clientes = listar_clientes(nv)
    salvar_csv("clientes.csv",
               [{"id_cliente": c["id_cliente"], "nome": c["nome"]} for c in clientes],
               ["id_cliente", "nome"])

    rel = relatorio_clientes(nv)
    if rel:
        salvar_csv("clientes_completo.csv", rel)

    print("\n[3/4] Extraindo histórico de cada animal...")
    todos_animais = []
    secoes_dados  = {k: [] for k in SECOES}
    ids = ["id_cliente", "id_animal", "nome_cliente", "nome_animal"]

    for i, cli in enumerate(clientes, 1):
        print(f"  [{i}/{len(clientes)}] {cli['nome']}")
        for animal in cli["animais"]:
            base = {"id_cliente": cli["id_cliente"], "id_animal": animal["id_animal"],
                    "nome_cliente": cli["nome"], "nome_animal": animal["nome_animal"]}
            todos_animais.append(dict(base))
            for nome_sec, php in SECOES.items():
                try:
                    soup = nv.get_soup(f"/admin/{php}",
                                       params={"id_cliente": base["id_cliente"],
                                               "id_animal": base["id_animal"]})
                    secoes_dados[nome_sec].extend(parse_tabela(soup, extra=base))
                except Exception as e:
                    print(f"    ✗ {nome_sec} ({animal['nome_animal']}): {e.__class__.__name__}")
                nv.sleep()

    salvar_csv("animais.csv", todos_animais, ids)
    for nome_sec, dados in secoes_dados.items():
        salvar_csv(f"{nome_sec}.csv", dados, ids)

    salvar_csv("retorno_vacinas.csv", retorno_vacinas(nv))
    print(f"\n✓ Concluído! Arquivos em {config.OUTPUT_DIR}/")


if __name__ == "__main__":
    main()