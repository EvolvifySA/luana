"""
scraper/tickets.py — Catálogo de serviços e histórico de tickets.

URLs confirmadas:
  tipos_de_servicos.php          → catálogo de serviços (clínica)
  tickets.php?id_cliente=X       → tickets do cliente

Gera servicos.csv e tickets.csv.   Uso:  python -m scraper.tickets
"""

import re
import config
from .client import NuvemVetClient, salvar_csv, ler_csv


def coletar_servicos(nv):
    print("\n[1/2] Coletando catálogo de serviços...")
    soup = nv.get_soup("/admin/tipos_de_servicos.php")
    tabela = soup.find("table") if soup else None
    if not tabela:
        print("  ✗ nenhuma tabela encontrada")
        return
    headers = [th.get_text(strip=True) for th in tabela.find_all("th")]
    servicos, vistos = [], set()
    for tr in tabela.find_all("tr")[1:]:
        cels = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if not any(cels):
            continue
        row = dict(zip(headers, cels)) if headers else {}
        nome = row.get("Nome do Serviço") or (cels[0] if cels else "")
        if nome in vistos:
            continue
        vistos.add(nome)
        row["tipo"] = "clinica"
        servicos.append(row)
    salvar_csv("servicos.csv", servicos)


def coletar_tickets(nv):
    print("\n[2/2] Coletando tickets de cada cliente...")
    clientes = ler_csv("clientes.csv")
    todos = []
    for i, cli in enumerate(clientes, 1):
        if i % 50 == 0:
            print(f"  [{i}/{len(clientes)}] {cli['nome']} — {len(todos)} tickets")
        try:
            soup = nv.get_soup("/admin/tickets.php", params={"id_cliente": cli["id_cliente"]})
            tabela = soup.find("table") if soup else None
            if not tabela:
                nv.sleep(); continue
            headers = [th.get_text(strip=True) for th in tabela.find_all("th")]
            for tr in tabela.find_all("tr")[1:]:
                cels = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
                if not any(cels):
                    continue
                row = dict(zip(headers, cels)) if headers else {}
                id_fin = id_ani = ""
                for a in tr.find_all("a", href=True):
                    m1 = re.search(r"id_financeiro=(\d+)", a["href"])
                    m2 = re.search(r"id_animal=(\d+)", a["href"])
                    if m1: id_fin = m1.group(1)
                    if m2: id_ani = m2.group(1)
                row.update({"id_cliente": cli["id_cliente"], "id_financeiro": id_fin, "id_animal": id_ani})
                todos.append(row)
        except Exception as e:
            print(f"    ✗ {cli['nome']}: {e.__class__.__name__}")
        nv.sleep()

    salvar_csv("tickets.csv", todos, ["id_cliente", "id_animal", "id_financeiro"])
    print(f"\n✓ {len(todos)} tickets coletados.")


def main():
    nv = NuvemVetClient()
    if not nv.login():
        return
    coletar_servicos(nv)
    coletar_tickets(nv)
    print("\n✓ Concluído!")


if __name__ == "__main__":
    main()