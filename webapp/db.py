"""
offline_db.py — Camada de dados do modo offline.

Lê exclusivamente de arquivos locais já exportados:
  - dados_exportados/clientes.csv
  - dados_exportados/clientes_completo.csv
  - dados_exportados/animais.csv
  - dados_exportados/consultas.csv
  - dados_exportados/exames.csv
  - dados_exportados/pesagens.csv
  - dados_exportados/retorno_vacinas.csv
  - dados_exportados/exames_pdf/   (PDFs locais)

Não faz nenhuma requisição HTTP externa.
Novos registros são salvos em offline_novos.db (SQLite local).
"""

import csv
import sqlite3
import os
import re
import logging
from functools import lru_cache

import config

# ─── LOG ──────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="[EVOLVIFY-DB] %(message)s"
)
log = logging.getLogger("evolvify_db")

# ─── CONFIGURAÇÃO ─────────────────────────────────────────────────────────────

OUTPUT_DIR = config.OUTPUT_DIR
NOVOS_DB   = "evolvify.db"

# Mapeamento confirmado por análise do clientes_completo.csv
# O parser HTML deslocou as colunas: o ID ficou vazio, e tudo avançou uma posição
# Confirmado com join 100% (580/580) e exemplos reais
COMPLETO_COLS = {
    "data_cadastro": "",          # header vazio = data de cadastro do cliente
    "nome":          "#",         # header '#' = nome real do cliente
    "cpf":           "Cadastro",  # header 'Cadastro' = CPF real
    "endereco":      "Nome",      # header 'Nome' = endereço real
    "celular":       "CPF",       # header 'CPF' = celular real
}

log.info("Mapeamento de colunas de clientes_completo.csv:")
for campo, col_csv in COMPLETO_COLS.items():
    log.info(f"  campo '{campo}' ← coluna CSV '{col_csv or '(vazio)'}'")


# ─── LEITURA DE CSV ───────────────────────────────────────────────────────────

def _ler_csv(nome_arquivo, delim=","):
    path = os.path.join(OUTPUT_DIR, nome_arquivo)
    if not os.path.exists(path):
        log.warning(f"Arquivo não encontrado: {path}")
        return []
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f, delimiter=delim))
    log.info(f"Carregado '{nome_arquivo}': {len(rows)} registros")
    return rows


# ─── CACHE DE DADOS ───────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _clientes_base():
    """clientes.csv — id_cliente e nome corretos."""
    return _ler_csv("clientes.csv")


@lru_cache(maxsize=1)
def _clientes_completo_idx():
    """
    Índice de clientes_completo.csv pelo nome (coluna '#').
    CPF está na coluna 'Cadastro', celular na coluna 'CPF'.
    """
    rows = _ler_csv("clientes_completo.csv")
    idx  = {}
    duplicados = []
    for row in rows:
        nome_key = (row.get(COMPLETO_COLS["nome"]) or "").strip().lower()
        if not nome_key:
            continue
        if nome_key in idx:
            duplicados.append(nome_key)
        else:
            idx[nome_key] = row

    if duplicados:
        log.warning(f"{len(duplicados)} nome(s) duplicado(s) em clientes_completo.csv "
                    f"(primeiro registro mantido): {duplicados}")
    log.info(f"Índice clientes_completo: {len(idx)} entradas únicas por nome")
    return idx


@lru_cache(maxsize=1)
def _animais():
    return _ler_csv("animais.csv")


@lru_cache(maxsize=1)
def _animais_detalhes_idx():
    """
    Índice de animais_detalhes.csv por (id_cliente, id_animal).
    Fonte: puxar_animais_detalhes.py
    """
    rows = _ler_csv("animais_detalhes.csv")
    idx  = {}
    for row in rows:
        key = (row.get("id_cliente", ""), row.get("id_animal", ""))
        idx[key] = row
    campos = set()
    for r in rows:
        campos.update(r.keys())
    log.info(f"animais_detalhes.csv campos: {sorted(campos - {'id_cliente','id_animal','nome_cliente','nome_animal'})}")
    return idx


@lru_cache(maxsize=1)
def _animais_idx():
    """Índice de animais por id_cliente, enriquecido com detalhes."""
    detalhes_idx = _animais_detalhes_idx()
    idx = {}
    for row in _animais():
        cid = row.get("id_cliente", "")
        aid = row.get("id_animal", "")
        # Junta com detalhes se disponível
        extra = detalhes_idx.get((cid, aid), {})
        animal = {**row, **extra}  # detalhes sobrescrevem campos básicos se houver
        idx.setdefault(cid, []).append(animal)
    return idx


def _registros(nome_csv):
    return _ler_csv(nome_csv)


def _registros_idx(nome_csv):
    """Índice de registros por (id_cliente, id_animal)."""
    idx = {}
    for row in _registros(nome_csv):
        key = (row.get("id_cliente", ""), row.get("id_animal", ""))
        idx.setdefault(key, []).append(row)
    return idx


SECAO_CSV = {
    "consultas":   "consultas.csv",
    "vacinas":     "vacinas.csv",
    "receituario": "receituario.csv",
    "exames":      "exames.csv",
    "cirurgias":   "cirurgias.csv",
    "pesagens":    "pesagens.csv",
    "anotacoes":   "anotacoes.csv",
}


# ─── BANCO DE NOVOS REGISTROS ─────────────────────────────────────────────────

def _get_novos_db():
    conn = sqlite3.connect(NOVOS_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clientes_novos (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            nome       TEXT NOT NULL,
            cpf        TEXT, celular TEXT, telefone TEXT,
            email      TEXT, endereco TEXT, cidade TEXT,
            nascimento TEXT, observacao TEXT,
            criado_em  TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS animais_novos (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            id_cliente TEXT, nome TEXT NOT NULL,
            especie    TEXT, raca TEXT, sexo TEXT,
            nascimento TEXT, pelagem TEXT, chip TEXT,
            observacao TEXT,
            criado_em  TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS registros_novos (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo       TEXT NOT NULL,
            id_cliente TEXT, id_animal TEXT,
            data       TEXT, descricao TEXT,
            veterinario TEXT, observacao TEXT, arquivo TEXT,
            criado_em  TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()
    return conn


# ─── CLIENTES ─────────────────────────────────────────────────────────────────

def _enriquecer(row_base, idx_completo):
    """
    Junta dados de clientes.csv com clientes_completo.csv pelo nome.
    Fonte dos campos:
      cpf      ← coluna 'Cadastro' de clientes_completo.csv
      celular  ← coluna 'CPF'      de clientes_completo.csv
      endereco ← coluna 'Nome'     de clientes_completo.csv
      cadastro ← coluna ''(vazia)  de clientes_completo.csv
    """
    nome_key = row_base.get("nome", "").strip().lower()
    extra    = idx_completo.get(nome_key)

    resultado = {
        "id_cliente": row_base.get("id_cliente", ""),
        "nome":       row_base.get("nome", ""),
        "cpf":        "",
        "celular":    "",
        "endereco":   "",
        "data_cadastro": "",
        "_fonte_cpf":     "não encontrado",
        "_fonte_celular": "não encontrado",
    }

    if extra:
        cpf     = (extra.get(COMPLETO_COLS["cpf"])      or "").strip()
        celular = (extra.get(COMPLETO_COLS["celular"])   or "").strip()
        end     = (extra.get(COMPLETO_COLS["endereco"])  or "").strip()
        data_c  = (extra.get(COMPLETO_COLS["data_cadastro"]) or "").strip()

        resultado["cpf"]          = cpf
        resultado["celular"]      = celular
        resultado["endereco"]     = end
        resultado["data_cadastro"]= data_c
        resultado["_fonte_cpf"]   = f"clientes_completo.csv → coluna 'Cadastro'"
        resultado["_fonte_celular"] = f"clientes_completo.csv → coluna 'CPF'"
    else:
        log.warning(f"Sem correspondência em clientes_completo para: '{row_base.get('nome')}'")

    return resultado


def buscar_clientes(q="", limite=50, offset=0):
    base_rows = _clientes_base()
    idx       = _clientes_completo_idx()

    if q:
        q_lower   = q.lower()
        base_rows = [r for r in base_rows
                     if q_lower in r.get("nome", "").lower()]

    pagina = base_rows[offset: offset + limite]
    return [_enriquecer(r, idx) for r in pagina]


def total_clientes():
    conn  = _get_novos_db()
    novos = conn.execute("SELECT COUNT(*) FROM clientes_novos").fetchone()[0]
    conn.close()
    return len(_clientes_base()) + novos


def get_cliente(id_cliente):
    id_str = str(id_cliente).replace("new_", "")

    # Tenta clientes importados
    for row in _clientes_base():
        if row.get("id_cliente") == id_str:
            idx = _clientes_completo_idx()
            enriched = _enriquecer(row, idx)
            log.info(f"Cliente {id_str}: CPF via {enriched['_fonte_cpf']}")
            return enriched

    # Tenta clientes novos
    conn = _get_novos_db()
    row  = conn.execute(
        "SELECT * FROM clientes_novos WHERE id = ?", (id_str,)
    ).fetchone()
    conn.close()
    if row:
        d = dict(row)
        d["id_cliente"] = f"new_{d['id']}"
        return d

    return None


# ─── ANIMAIS ──────────────────────────────────────────────────────────────────

def get_animais_cliente(id_cliente):
    id_str  = str(id_cliente).replace("new_", "")
    idx     = _animais_idx()
    animais = idx.get(id_str, [])

    conn   = _get_novos_db()
    novos  = conn.execute(
        "SELECT * FROM animais_novos WHERE id_cliente = ?", (id_str,)
    ).fetchall()
    conn.close()

    log.info(f"Animais para cliente {id_str}: "
             f"{len(animais)} importados + {len(novos)} novos "
             f"(fonte: animais.csv + offline_novos.db)")

    return animais + [dict(r) for r in novos]


def total_animais():
    return len(_animais())


# ─── REGISTROS ────────────────────────────────────────────────────────────────

def get_registros_animal(id_cliente, id_animal, secao):
    nome_csv = SECAO_CSV.get(secao)
    key      = (str(id_cliente), str(id_animal))
    importados = []

    if nome_csv:
        idx        = _registros_idx(nome_csv)
        importados = idx.get(key, [])
        log.info(f"Seção '{secao}' para animal {id_animal}: "
                 f"{len(importados)} registros de {nome_csv}")
    else:
        log.warning(f"Seção '{secao}' sem arquivo CSV mapeado")

    conn  = _get_novos_db()
    novos = conn.execute(
        "SELECT * FROM registros_novos WHERE tipo = ? AND id_cliente = ? AND id_animal = ?",
        (secao.rstrip("s"), str(id_cliente), str(id_animal))
    ).fetchall()
    conn.close()

    return importados + [dict(r) for r in novos]


def total_registros(secao):
    nome_csv = SECAO_CSV.get(secao)
    if not nome_csv:
        return 0
    rows = _registros(nome_csv)
    return len(rows)


# ─── INSERÇÕES ────────────────────────────────────────────────────────────────

def inserir_cliente(dados):
    conn = _get_novos_db()
    conn.execute(
        """INSERT INTO clientes_novos
           (nome,cpf,celular,telefone,email,endereco,cidade,nascimento,observacao)
           VALUES (:nome,:cpf,:celular,:telefone,:email,:endereco,:cidade,:nascimento,:observacao)""",
        dados,
    )
    conn.commit()
    id_novo = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    log.info(f"Novo cliente inserido: id=new_{id_novo}, nome={dados.get('nome')}")
    return id_novo


def inserir_animal(dados):
    conn = _get_novos_db()
    conn.execute(
        """INSERT INTO animais_novos
           (id_cliente,nome,especie,raca,sexo,nascimento,pelagem,chip,observacao)
           VALUES (:id_cliente,:nome,:especie,:raca,:sexo,:nascimento,:pelagem,:chip,:observacao)""",
        dados,
    )
    conn.commit()
    id_novo = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    log.info(f"Novo animal inserido: id={id_novo}, nome={dados.get('nome')}")
    return id_novo


def inserir_registro(dados):
    conn = _get_novos_db()
    conn.execute(
        """INSERT INTO registros_novos
           (tipo,id_cliente,id_animal,data,descricao,veterinario,observacao,arquivo)
           VALUES (:tipo,:id_cliente,:id_animal,:data,:descricao,:veterinario,:observacao,:arquivo)""",
        dados,
    )
    conn.commit()
    conn.close()
    log.info(f"Novo registro inserido: tipo={dados.get('tipo')}, animal={dados.get('id_animal')}")


# ─── SERVIÇOS ─────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_servicos():
    """Retorna catálogo de serviços do servicos.csv."""
    rows = _ler_csv("servicos.csv")
    log.info(f"Catálogo de serviços: {len(rows)} itens (fonte: servicos.csv)")
    return rows


# ─── TICKETS ──────────────────────────────────────────────────────────────────

def _init_tickets_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            id_cliente     TEXT,
            id_animal      TEXT,
            nome_cliente   TEXT,
            nome_animal    TEXT,
            data           TEXT,
            veterinario    TEXT,
            cpf            TEXT,
            celular        TEXT,
            email          TEXT,
            endereco       TEXT,
            cidade         TEXT,
            especie        TEXT,
            raca           TEXT,
            pelagem        TEXT,
            nascimento     TEXT,
            sexo           TEXT,
            chip           TEXT,
            itens_json     TEXT,
            total_servicos TEXT,
            total_produtos TEXT,
            total_bruto    TEXT,
            total_descontos TEXT,
            total_liquido  TEXT,
            criado_em      TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()


def proximo_id_ticket():
    conn = _get_novos_db()
    _init_tickets_table(conn)
    n = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
    conn.close()
    return n + 1


def salvar_ticket(ticket):
    import json as _json
    conn = _get_novos_db()
    _init_tickets_table(conn)
    conn.execute("""
        INSERT INTO tickets
        (id_cliente,id_animal,nome_cliente,nome_animal,data,veterinario,
         cpf,celular,email,endereco,cidade,especie,raca,pelagem,nascimento,
         sexo,chip,itens_json,total_servicos,total_produtos,total_bruto,
         total_descontos,total_liquido)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        ticket.get("id_cliente"), ticket.get("id_animal"),
        ticket.get("nome_cliente"), ticket.get("nome_animal"),
        ticket.get("data"), ticket.get("veterinario"),
        ticket.get("cpf"), ticket.get("celular"),
        ticket.get("email"), ticket.get("endereco"), ticket.get("cidade"),
        ticket.get("especie"), ticket.get("raca"), ticket.get("pelagem"),
        ticket.get("nascimento"), ticket.get("sexo"), ticket.get("chip"),
        _json.dumps(ticket.get("itens", []), ensure_ascii=False),
        ticket.get("total_servicos"), ticket.get("total_produtos"),
        ticket.get("total_bruto"), ticket.get("total_descontos"),
        ticket.get("total_liquido"),
    ))
    conn.commit()
    conn.close()
    log.info(f"Ticket salvo: cliente={ticket.get('nome_cliente')}, animal={ticket.get('nome_animal')}")


def get_ticket(ticket_id):
    import json as _json
    conn = _get_novos_db()
    _init_tickets_table(conn)
    row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    conn.close()
    if not row:
        return None
    t = dict(row)
    t["itens"] = _json.loads(t.get("itens_json") or "[]")
    return t


@lru_cache(maxsize=1)
def _tickets_importados_idx():
    """Índice de tickets.csv por id_cliente."""
    rows = _ler_csv("tickets.csv")
    idx  = {}
    for row in rows:
        cid = row.get("id_cliente", "")
        idx.setdefault(cid, []).append(row)
    return idx


def get_tickets_cliente(id_cliente):
    """
    Retorna tickets de um cliente: importados (tickets.csv) + criados no offline.
    """
    id_str = str(id_cliente).replace("new_", "")

    # Importados do NuvemVet
    importados = _tickets_importados_idx().get(id_str, [])

    # Criados no sistema offline
    conn = _get_novos_db()
    _init_tickets_table(conn)
    novos = conn.execute(
        "SELECT * FROM tickets WHERE id_cliente = ? ORDER BY id DESC", (id_str,)
    ).fetchall()
    conn.close()

    log.info(f"Tickets cliente {id_str}: {len(importados)} importados + {len(novos)} criados")
    return importados, [dict(r) for r in novos]


# ─── RECEITAS ─────────────────────────────────────────────────────────────────

def _init_receitas_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS receitas (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            id_cliente   TEXT,
            id_animal    TEXT,
            tipo         TEXT,          -- 'simples' | 'especial'
            data         TEXT,
            veterinario  TEXT,
            crmv         TEXT,
            uso_oral     TEXT,          -- texto, um medicamento por linha
            uso_topico   TEXT,
            observacao   TEXT,
            criado_em    TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()


def salvar_receita(dados):
    conn = _get_novos_db()
    _init_receitas_table(conn)
    conn.execute("""
        INSERT INTO receitas
        (id_cliente,id_animal,tipo,data,veterinario,crmv,uso_oral,uso_topico,observacao)
        VALUES (:id_cliente,:id_animal,:tipo,:data,:veterinario,:crmv,:uso_oral,:uso_topico,:observacao)
    """, dados)
    conn.commit()
    rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    log.info(f"Receita salva: id={rid}, tipo={dados.get('tipo')}, animal={dados.get('id_animal')}")
    return rid


def get_receita(receita_id):
    conn = _get_novos_db()
    _init_receitas_table(conn)
    row = conn.execute("SELECT * FROM receitas WHERE id = ?", (receita_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_receitas_animal(id_cliente, id_animal):
    conn = _get_novos_db()
    _init_receitas_table(conn)
    rows = conn.execute(
        "SELECT * FROM receitas WHERE id_cliente = ? AND id_animal = ? ORDER BY id DESC",
        (str(id_cliente), str(id_animal))
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── USUÁRIOS / LOGIN ─────────────────────────────────────────────────────────

def _init_usuarios_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            username   TEXT UNIQUE NOT NULL,
            senha_hash TEXT NOT NULL,
            nome       TEXT,
            criado_em  TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()


def garantir_usuario_padrao():
    """Cria o usuário padrão da Luana se nenhum existir. Retorna (username, senha) se criou."""
    from werkzeug.security import generate_password_hash
    conn = _get_novos_db()
    _init_usuarios_table(conn)
    n = conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
    if n == 0:
        username, senha = "luana", "evolvify2026"
        conn.execute(
            "INSERT INTO usuarios (username, senha_hash, nome) VALUES (?,?,?)",
            (username, generate_password_hash(senha), "Luana Feitosa")
        )
        conn.commit()
        conn.close()
        log.info(f"Usuário padrão criado: {username} / {senha}")
        return username, senha
    conn.close()
    return None


def verificar_login(username, senha):
    """Retorna dict do usuário se as credenciais conferem, senão None."""
    from werkzeug.security import check_password_hash
    conn = _get_novos_db()
    _init_usuarios_table(conn)
    row = conn.execute(
        "SELECT * FROM usuarios WHERE username = ?", (username.strip().lower(),)
    ).fetchone()
    conn.close()
    if row and check_password_hash(row["senha_hash"], senha):
        return {"id": row["id"], "username": row["username"], "nome": row["nome"]}
    return None


def trocar_senha(user_id, senha_nova):
    from werkzeug.security import generate_password_hash
    conn = _get_novos_db()
    _init_usuarios_table(conn)
    conn.execute("UPDATE usuarios SET senha_hash = ? WHERE id = ?",
                 (generate_password_hash(senha_nova), user_id))
    conn.commit()
    conn.close()
    log.info(f"Senha alterada para usuário id={user_id}")


# ─── FINANCEIRO ───────────────────────────────────────────────────────────────

def _parse_valor(texto):
    """Converte 'R$ 1.234,56' ou '700,00' em float."""
    if not texto:
        return 0.0
    s = str(texto).replace("R$", "").replace(" ", "").strip()
    s = re.sub(r"\.(?=\d{3})", "", s)   # remove ponto de milhar
    s = s.replace(",", ".")
    try:
        return float(re.findall(r"-?\d+\.?\d*", s)[0])
    except (ValueError, IndexError):
        return 0.0


def _parse_data(texto):
    """Extrai (ano, mes) de uma data DD/MM/AAAA ou DD-MM-AAAA. Retorna None se falhar."""
    if not texto:
        return None
    m = re.search(r"(\d{2})[/-](\d{2})[/-](\d{4})", str(texto))
    if m:
        return (int(m.group(3)), int(m.group(2)))
    return None


def _todos_tickets():
    """
    Unifica tickets importados (tickets.csv) + criados no offline.
    Retorna lista de dicts normalizados: {data, valor, pago, cliente, animal, origem}.
    """
    unificados = []

    # Importados
    for t in _ler_csv("tickets.csv"):
        status = (t.get("Status") or "").lower()
        valor  = _parse_valor(t.get("Valor Final") or t.get("Valor Ticket") or "0")
        unificados.append({
            "data":    t.get("Data") or t.get("Registrado") or "",
            "valor":   valor,
            "pago":    "pago" in status and "pendente" not in status.replace("pago", "", 1),
            "status":  t.get("Status") or "",
            "cliente": t.get("Cliente") or "",
            "animal":  t.get("Animal") or "",
            "numero":  t.get("Nº ticket") or t.get("N ticket") or t.get("id_financeiro") or "",
            "id_cliente": t.get("id_cliente", ""),
            "origem":  "importado",
        })

    # Criados no offline
    conn = _get_novos_db()
    _init_tickets_table(conn)
    rows = conn.execute("SELECT * FROM tickets").fetchall()
    conn.close()
    for r in rows:
        d = dict(r)
        unificados.append({
            "data":    d.get("data") or "",
            "valor":   _parse_valor(d.get("total_liquido") or "0"),
            "pago":    True,   # tickets criados são considerados realizados
            "status":  "Pago",
            "cliente": d.get("nome_cliente") or "",
            "animal":  d.get("nome_animal") or "",
            "numero":  f"OFF-{d.get('id')}",
            "id_cliente": d.get("id_cliente", ""),
            "origem":  "offline",
        })

    return unificados


def resumo_financeiro():
    """Retorna métricas agregadas para o dashboard financeiro."""
    tickets = _todos_tickets()

    total_geral    = sum(t["valor"] for t in tickets)
    total_recebido = sum(t["valor"] for t in tickets if t["pago"])
    total_pendente = total_geral - total_recebido
    qtd_tickets    = len(tickets)
    qtd_pagos      = sum(1 for t in tickets if t["pago"])

    # Fluxo dos últimos 12 meses
    from collections import OrderedDict
    import datetime
    hoje = datetime.date.today()
    meses = OrderedDict()
    for i in range(11, -1, -1):
        ano = hoje.year
        mes = hoje.month - i
        while mes <= 0:
            mes += 12
            ano -= 1
        meses[(ano, mes)] = 0.0

    for t in tickets:
        ym = _parse_data(t["data"])
        if ym and ym in meses and t["pago"]:
            meses[ym] += t["valor"]

    nomes_mes = ["", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
                 "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    fluxo = [{"label": f"{nomes_mes[m]}/{str(a)[2:]}", "valor": round(v, 2)}
             for (a, m), v in meses.items()]

    log.info(f"Resumo financeiro: {qtd_tickets} tickets, "
             f"recebido R${total_recebido:.2f}, pendente R${total_pendente:.2f}")

    return {
        "total_geral":    round(total_geral, 2),
        "total_recebido": round(total_recebido, 2),
        "total_pendente": round(total_pendente, 2),
        "qtd_tickets":    qtd_tickets,
        "qtd_pagos":      qtd_pagos,
        "qtd_pendentes":  qtd_tickets - qtd_pagos,
        "fluxo":          fluxo,
        "fluxo_max":      max((f["valor"] for f in fluxo), default=0) or 1,
    }


def ultimos_tickets(limite=15):
    """Retorna os tickets mais recentes (por data) para a tabela do dashboard."""
    tickets = _todos_tickets()

    def chave_data(t):
        ym = _parse_data(t["data"])
        m  = re.search(r"(\d{2})[/-](\d{2})[/-](\d{4})", str(t["data"]))
        if m:
            return (int(m.group(3)), int(m.group(2)), int(m.group(1)))
        return (0, 0, 0)

    tickets.sort(key=chave_data, reverse=True)
    return tickets[:limite]
