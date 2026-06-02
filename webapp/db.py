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


def _parse_bool(valor):
    if valor is None:
        return None
    if isinstance(valor, bool):
        return valor
    texto = str(valor).strip().lower()
    if texto in {"1", "true", "sim", "s", "yes", "y", "on"}:
        return True
    if texto in {"0", "false", "nao", "não", "n", "no", "off"}:
        return False
    return None


def _parse_date(valor):
    if not valor:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    from datetime import datetime
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    return None


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


# =============================================================================
# Postgres / Supabase
# =============================================================================

_LEGACY_garantir_usuario_padrao = garantir_usuario_padrao
_LEGACY_verificar_login = verificar_login
_LEGACY_trocar_senha = trocar_senha
_LEGACY_total_clientes = total_clientes
_LEGACY_total_animais = total_animais
_LEGACY_total_registros = total_registros
_LEGACY_buscar_clientes = buscar_clientes
_LEGACY_get_cliente = get_cliente
_LEGACY_get_animais_cliente = get_animais_cliente
_LEGACY_get_registros_animal = get_registros_animal
_LEGACY_inserir_cliente = inserir_cliente
_LEGACY_inserir_animal = inserir_animal
_LEGACY_inserir_registro = inserir_registro
_LEGACY_get_servicos = get_servicos
_LEGACY_proximo_id_ticket = proximo_id_ticket
_LEGACY_salvar_ticket = salvar_ticket
_LEGACY_get_ticket = get_ticket
_LEGACY_get_tickets_cliente = get_tickets_cliente
_LEGACY_salvar_receita = salvar_receita
_LEGACY_get_receita = get_receita
_LEGACY_get_receitas_animal = get_receitas_animal
_LEGACY_resumo_financeiro = resumo_financeiro
_LEGACY_ultimos_tickets = ultimos_tickets

try:
    import json
    import socket
    from urllib.parse import urlsplit, parse_qs, unquote
    import psycopg2
    from psycopg2.extras import RealDictCursor, Json
except Exception:  # pragma: no cover - fallback when psycopg2 is unavailable
    psycopg2 = None
    RealDictCursor = None
    Json = None


def _json_dumps(value):
    return json.dumps(value, ensure_ascii=False, default=str)


def _pg_enabled():
    return bool(getattr(config, "DATABASE_URL", "").strip()) and psycopg2 is not None


def _pg_conn():
    dsn = getattr(config, "DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("DATABASE_URL não configurado.")

    parsed = urlsplit(dsn)
    if parsed.hostname:
        host = parsed.hostname
        port = parsed.port or 5432
        user = unquote(parsed.username or "")
        password = unquote(parsed.password or "")
        database = parsed.path.lstrip("/") or "postgres"
        query = parse_qs(parsed.query)
        sslmode = (query.get("sslmode") or ["require"])[0]

        try:
            ipv4 = None
            for family, _, _, _, sockaddr in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM):
                if family == socket.AF_INET:
                    ipv4 = sockaddr[0]
                    break

            if ipv4:
                return psycopg2.connect(
                    dbname=database,
                    user=user,
                    password=password,
                    host=host,
                    hostaddr=ipv4,
                    port=port,
                    sslmode=sslmode,
                )
        except socket.gaierror:
            pass

    return psycopg2.connect(dsn)


def _pg_fetchall(sql, params=()):
    with _pg_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


def _pg_fetchone(sql, params=()):
    with _pg_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None


def _map_client_row(row):
    if not row:
        return None
    created_at = row.get("created_at")
    return {
        "id_cliente": str(row["id"]),
        "nome": row.get("name") or "",
        "cpf": row.get("cpf") or "",
        "celular": row.get("mobile") or "",
        "telefone": row.get("phone") or "",
        "email": row.get("email") or "",
        "endereco": row.get("address") or "",
        "cidade": row.get("city") or "",
        "bairro": row.get("neighborhood") or "",
        "estado": row.get("state") or "",
        "cep": row.get("zip_code") or "",
        "data_cadastro": created_at.strftime("%d/%m/%Y") if created_at else "",
        "criado_em": created_at.isoformat() if created_at else "",
        "nascimento": row.get("birth_date").isoformat() if row.get("birth_date") else "",
        "observacao": row.get("notes") or "",
        "source": row.get("source") or "",
        "legacy_client_id": row.get("legacy_client_id") or "",
    }


def _map_animal_row(row):
    if not row:
        return None
    castrado = row.get("castrado")
    castrado_label = ""
    if castrado is True:
        castrado_label = "SIM"
    elif castrado is False:
        castrado_label = "NÃO"
    return {
        "id_animal": str(row["id"]),
        "id_cliente": str(row["client_id"]),
        "nome": row.get("name") or "",
        "nome_animal": row.get("name") or "",
        "especie": row.get("species") or "",
        "raca": row.get("breed") or "",
        "sexo": row.get("sex") or "",
        "nascimento": row.get("birth_date").isoformat() if row.get("birth_date") else "",
        "pelagem": row.get("coat") or "",
        "chip": row.get("chip") or "",
        "castrado": castrado,
        "castrado_label": castrado_label,
        "observacao": row.get("notes") or "",
        "source": row.get("source") or "",
        "legacy_animal_id": row.get("legacy_animal_id") or "",
    }


def _map_consultation_row(row):
    if not row:
        return None
    return {
        "id": str(row["id"]),
        "id_cliente": str(row["client_id"]),
        "id_animal": str(row["animal_id"]) if row.get("animal_id") else "",
        "data_da_consulta": row["consultation_date"].isoformat() if row.get("consultation_date") else "",
        "consultation_date": row["consultation_date"].isoformat() if row.get("consultation_date") else "",
        "is_retorno": bool(row.get("is_return")),
        "is_return": bool(row.get("is_return")),
        "data_retorno": row["return_date"].isoformat() if row.get("return_date") else "",
        "return_date": row["return_date"].isoformat() if row.get("return_date") else "",
        "status": row.get("status") or "draft",
        "chief_complaint": row.get("chief_complaint") or "",
        "queixa_principal": row.get("chief_complaint") or "",
        "anamnesis": row.get("anamnesis") or "",
        "anamnese": row.get("anamnesis") or "",
        "digestive_system": row.get("digestive_system") or "",
        "sistema_digestorio": row.get("digestive_system") or "",
        "cardiorespiratory_system": row.get("cardiorespiratory_system") or "",
        "sistema_cardiorrespiratorio": row.get("cardiorespiratory_system") or "",
        "genitourinary_system": row.get("genitourinary_system") or "",
        "sistema_genito_urinario": row.get("genitourinary_system") or "",
        "nervous_musculoskeletal_system": row.get("nervous_musculoskeletal_system") or "",
        "sistema_nervoso_locomotor": row.get("nervous_musculoskeletal_system") or "",
        "central_temperature": row.get("central_temperature") or "",
        "peripheral_temperature": row.get("peripheral_temperature") or "",
        "freq_cardiaca": row.get("heart_rate") or "",
        "heart_rate": row.get("heart_rate") or "",
        "freq_respiratoria": row.get("respiratory_rate") or "",
        "respiratory_rate": row.get("respiratory_rate") or "",
        "tpc": row.get("tpc") or "",
        "linfonodos": row.get("lymph_nodes") or "",
        "mucosa": row.get("mucosa") or "",
        "hidratacao": row.get("hydration") or "",
        "ectoparasitas": row.get("ectoparasites") or "",
        "palpacao_abdominal": row.get("abdominal_palpation") or "",
        "ausculta_cardiaca": row.get("cardiac_auscultation") or "",
        "ausculta_pulmonar": row.get("pulmonary_auscultation") or "",
        "pressao_arterial": row.get("blood_pressure") or "",
        "glicemia": row.get("glycemia") or "",
        "delta": row.get("delta") or "",
        "peso": row.get("weight") or "",
        "clinical_suspicion": row.get("clinical_suspicion") or "",
        "suspeita_clinica": row.get("clinical_suspicion") or "",
        "requested_exams": row.get("requested_exams") or "",
        "exames_solicitados": row.get("requested_exams") or "",
        "diagnosis": row.get("diagnosis") or "",
        "diagnostico": row.get("diagnosis") or "",
        "outpatient_treatment": row.get("outpatient_treatment") or "",
        "tratamento_ambulatorial": row.get("outpatient_treatment") or "",
        "integumentary_system": row.get("integumentary_system") or "",
        "sistema_tegumentares_anexos": row.get("integumentary_system") or "",
        "previous_diseases_treatments": row.get("previous_diseases_treatments") or "",
        "doencas_tratamentos_anteriores": row.get("previous_diseases_treatments") or "",
        "observations": row.get("observations") or row.get("notes") or "",
        "observacoes": row.get("observations") or row.get("notes") or "",
        "veterinarian": row.get("veterinarian") or "",
        "veterinario": row.get("veterinarian") or "",
        "crmv": row.get("crmv") or "",
        "completed_at": row.get("completed_at").isoformat() if row.get("completed_at") else "",
        "finalizado_em": row.get("completed_at").isoformat() if row.get("completed_at") else "",
        "completed_by": row.get("completed_by") or "",
        "finalizado_por": row.get("completed_by") or "",
        "source": row.get("source") or "",
        "source_payload": row.get("source_payload") or {},
        "legacy_consultation_id": row.get("legacy_consultation_id") or "",
    }


def _resolve_client_pg(id_cliente):
    clean = str(id_cliente).replace("new_", "")
    row = _pg_fetchone(
        """
        select *
          from public.clients
         where id::text = %s
            or legacy_client_id = %s
            or name = %s
         limit 1
        """,
        (clean, clean, clean),
    )
    return row


def _resolve_animal_pg(id_animal):
    clean = str(id_animal).replace("new_", "")
    row = _pg_fetchone(
        """
        select *
          from public.animals
         where id::text = %s
            or legacy_animal_id = %s
         limit 1
        """,
        (clean, clean),
    )
    return row


def _resolve_ticket_row(ticket_id):
    return _pg_fetchone("select * from public.tickets where id::text = %s limit 1", (str(ticket_id),))


def _resolve_receita_row(receita_id):
    return _pg_fetchone("select * from public.prescriptions where id::text = %s limit 1", (str(receita_id),))


def _resolve_consultation_row(consulta_id):
    return _pg_fetchone("select * from public.consultations where id::text = %s limit 1", (str(consulta_id),))


def garantir_usuario_padrao():
    if not _pg_enabled():
        return _LEGACY_garantir_usuario_padrao()
    from werkzeug.security import generate_password_hash

    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from public.users")
            total = cur.fetchone()[0]
            if total == 0:
                cur.execute(
                    """
                    insert into public.users (username, password_hash, full_name, role, active)
                    values (%s, %s, %s, %s, true)
                    """,
                    ("luana", generate_password_hash("evolvify2026"), "Luana Feitosa", "admin"),
                )
                conn.commit()
                return ("luana", "evolvify2026")
    return None


def verificar_login(username, senha):
    if not _pg_enabled():
        return _LEGACY_verificar_login(username, senha)
    from werkzeug.security import check_password_hash

    row = _pg_fetchone(
        "select id, username, full_name, password_hash from public.users where lower(username) = lower(%s) limit 1",
        (username.strip(),),
    )
    if row and check_password_hash(row["password_hash"], senha):
        return {"id": row["id"], "username": row["username"], "nome": row.get("full_name") or row["username"]}
    return None


def trocar_senha(user_id, senha_nova):
    if not _pg_enabled():
        return _LEGACY_trocar_senha(user_id, senha_nova)
    from werkzeug.security import generate_password_hash

    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update public.users set password_hash = %s, updated_at = now() where id::text = %s",
                (generate_password_hash(senha_nova), str(user_id)),
            )
        conn.commit()


def total_clientes():
    if not _pg_enabled():
        return _LEGACY_total_clientes()
    row = _pg_fetchone("select count(*) as n from public.clients")
    return int(row["n"]) if row else 0


def total_animais():
    if not _pg_enabled():
        return _LEGACY_total_animais()
    row = _pg_fetchone("select count(*) as n from public.animals")
    return int(row["n"]) if row else 0


def total_registros(secao):
    if not _pg_enabled():
        return _LEGACY_total_registros(secao)
    table_map = {
        "consultas": "consultations",
        "vacinas": "vaccinations",
        "receituario": "prescriptions",
        "exames": "exams",
        "cirurgias": "surgeries",
        "pesagens": "weights",
        "anotacoes": "notes",
    }
    table = table_map.get(secao)
    if not table:
        return 0
    row = _pg_fetchone(f"select count(*) as n from public.{table}")
    return int(row["n"]) if row else 0


def buscar_clientes(q="", limite=50, offset=0):
    if not _pg_enabled():
        return _LEGACY_buscar_clientes(q=q, limite=limite, offset=offset)
    params = [limite, offset]
    where = ""
    if q:
        where = "where lower(coalesce(name, '')) like lower(%s)"
        params = [f"%{q}%", limite, offset]
    rows = _pg_fetchall(
        f"""
        select *
          from public.clients
          {where}
         order by lower(name)
         limit %s offset %s
        """,
        tuple(params),
    )
    return [_map_client_row(r) for r in rows]


def get_cliente(id_cliente):
    if not _pg_enabled():
        return _LEGACY_get_cliente(id_cliente)
    row = _resolve_client_pg(id_cliente)
    if row:
        return _map_client_row(row)
    return _LEGACY_get_cliente(id_cliente)


def get_animais_cliente(id_cliente):
    if not _pg_enabled():
        return _LEGACY_get_animais_cliente(id_cliente)
    client = _resolve_client_pg(id_cliente)
    if not client:
        return _LEGACY_get_animais_cliente(id_cliente)
    rows = _pg_fetchall("select * from public.animals where client_id = %s order by lower(name)", (client["id"],))
    animais = [_map_animal_row(r) for r in rows]
    if animais:
        return animais
    return _LEGACY_get_animais_cliente(id_cliente)


def get_registros_animal(id_cliente, id_animal, secao):
    if not _pg_enabled():
        return _LEGACY_get_registros_animal(id_cliente, id_animal, secao)
    client = _resolve_client_pg(id_cliente)
    animal = _resolve_animal_pg(id_animal)
    if not client or not animal:
        return _LEGACY_get_registros_animal(id_cliente, id_animal, secao)

    if secao == "consultas":
        rows = _pg_fetchall(
            """select id, consultation_date as data, coalesce(chief_complaint, notes, '') as descricao,
                      veterinarian, diagnosis, observations, is_return, return_date, status, source_payload
                 from public.consultations
                where client_id = %s and animal_id = %s
                order by consultation_date desc""",
            (client["id"], animal["id"]),
        )
    elif secao == "vacinas":
        rows = _pg_fetchall(
            """select applied_at as data, vaccine_name as descricao, veterinarian, notes, source_payload
                 from public.vaccinations
                where client_id = %s and animal_id = %s
                order by applied_at desc""",
            (client["id"], animal["id"]),
        )
    elif secao == "exames":
        rows = _pg_fetchall(
            """select exam_date as data, exam_type as descricao, requester as veterinarian, notes, source_payload
                 from public.exams
                where client_id = %s and animal_id = %s
                order by exam_date desc""",
            (client["id"], animal["id"]),
        )
    elif secao == "cirurgias":
        rows = _pg_fetchall(
            """select surgery_date as data, title as descricao, veterinarian, notes, source_payload
                 from public.surgeries
                where client_id = %s and animal_id = %s
                order by surgery_date desc""",
            (client["id"], animal["id"]),
        )
    elif secao == "pesagens":
        rows = _pg_fetchall(
            """select weighed_at as data, weight::text as descricao, recorded_by as veterinarian, notes, source_payload
                 from public.weights
                where client_id = %s and animal_id = %s
                order by weighed_at desc""",
            (client["id"], animal["id"]),
        )
    else:
        rows = _pg_fetchall(
            """select note_date as data, title as descricao, veterinarian, body as notes, source_payload
                 from public.notes
                where client_id = %s and animal_id = %s
                order by note_date desc""",
            (client["id"], animal["id"]),
        )

    if not rows:
        return _LEGACY_get_registros_animal(id_cliente, id_animal, secao)
    return [
        {
            "id": str(r.get("id")) if r.get("id") else "",
            "data": (r.get("data").strftime("%d/%m/%Y") if r.get("data") else ""),
            "descricao": r.get("descricao") or "",
            "veterinario": r.get("veterinarian") or "",
            "observacao": r.get("observations") or r.get("notes") or "",
            "diagnostico": r.get("diagnosis") or "",
            "status": r.get("status") or "",
            "retorno": "Sim" if r.get("is_return") else "Não",
            "retorno_data": r.get("return_date").strftime("%d/%m/%Y") if r.get("return_date") else "",
        }
        for r in rows
    ]


def atualizar_status_ticket(ticket_id, status):
    if not _pg_enabled():
        raise RuntimeError("Atualização de status do ticket disponível apenas no Postgres.")
    status = (status or "").strip().lower()
    if status not in {"paid", "pending", "cancelled", "draft"}:
        raise ValueError("Status inválido para ticket.")
    ticket = _resolve_ticket_row(ticket_id)
    if not ticket:
        raise ValueError("Ticket não encontrado.")
    with _pg_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "update public.tickets set status = %s where id = %s returning id",
                (status, ticket["id"]),
            )
            row = cur.fetchone()
        conn.commit()
    return str(row["id"]) if row else str(ticket["id"])


def inserir_cliente(dados):
    if not _pg_enabled():
        return _LEGACY_inserir_cliente(dados)
    with _pg_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                insert into public.clients (name, cpf, mobile, phone, email, address, city, neighborhood, state, zip_code, birth_date, notes, source)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'manual')
                returning id
                """,
                (
                    dados.get("nome"),
                    dados.get("cpf"),
                    dados.get("celular"),
                    dados.get("telefone"),
                    dados.get("email"),
                    dados.get("endereco"),
                    dados.get("cidade"),
                    dados.get("bairro"),
                    dados.get("estado"),
                    dados.get("cep") or dados.get("zip_code"),
                    dados.get("nascimento") or None,
                    dados.get("observacao"),
                ),
            )
            new_id = str(cur.fetchone()["id"])
        conn.commit()
    return new_id


def inserir_animal(dados):
    if not _pg_enabled():
        return _LEGACY_inserir_animal(dados)
    client = _resolve_client_pg(dados.get("id_cliente"))
    if not client:
        raise ValueError("Cliente não encontrado para inserir animal.")
    with _pg_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                insert into public.animals (client_id, name, species, breed, sex, birth_date, coat, chip, castrado, notes, source)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'manual')
                returning id
                """,
                (
                    client["id"],
                    dados.get("nome"),
                    dados.get("especie"),
                    dados.get("raca"),
                    dados.get("sexo"),
                    dados.get("nascimento") or None,
                    dados.get("pelagem"),
                    dados.get("chip"),
                    _parse_bool(dados.get("castrado")),
                    dados.get("observacao"),
                ),
            )
            new_id = str(cur.fetchone()["id"])
        conn.commit()
    return new_id


def inserir_registro(dados):
    if not _pg_enabled():
        return _LEGACY_inserir_registro(dados)
    client = _resolve_client_pg(dados.get("id_cliente"))
    animal = _resolve_animal_pg(dados.get("id_animal"))
    if not client or not animal:
        raise ValueError("Cliente ou animal não encontrado para registrar histórico.")
    secao = (dados.get("tipo") or "").rstrip("s")
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            if secao == "consulta":
                cur.execute(
                    """
                    insert into public.consultations (client_id, animal_id, consultation_date, veterinarian, notes, source)
                    values (%s,%s,%s,%s,%s,'manual')
                    """,
                    (client["id"], animal["id"], dados.get("data") or None, dados.get("veterinario"), dados.get("observacao") or dados.get("descricao")),
                )
            elif secao == "vacina":
                cur.execute(
                    """
                    insert into public.vaccinations (client_id, animal_id, vaccine_name, applied_at, veterinarian, notes, source)
                    values (%s,%s,%s,%s,%s,%s,'manual')
                    """,
                    (client["id"], animal["id"], dados.get("descricao"), dados.get("data") or None, dados.get("veterinario"), dados.get("observacao")),
                )
            elif secao == "exame":
                cur.execute(
                    """
                    insert into public.exams (client_id, animal_id, exam_date, exam_type, requester, notes, source, source_url, requires_browser)
                    values (%s,%s,%s,%s,%s,%s,'manual',%s,false)
                    """,
                    (client["id"], animal["id"], dados.get("data") or None, dados.get("descricao"), dados.get("veterinario"), dados.get("observacao"), dados.get("arquivo") or None),
                )
            elif secao == "cirurgia":
                cur.execute(
                    """
                    insert into public.surgeries (client_id, animal_id, surgery_date, title, veterinarian, notes, source)
                    values (%s,%s,%s,%s,%s,%s,'manual')
                    """,
                    (client["id"], animal["id"], dados.get("data") or None, dados.get("descricao"), dados.get("veterinario"), dados.get("observacao")),
                )
            elif secao == "pesagem":
                cur.execute(
                    """
                    insert into public.weights (client_id, animal_id, weighed_at, weight, recorded_by, notes, source)
                    values (%s,%s,%s,%s,%s,%s,'manual')
                    """,
                    (client["id"], animal["id"], dados.get("data") or None, _parse_valor(dados.get("descricao")), dados.get("veterinario"), dados.get("observacao")),
                )
            else:
                cur.execute(
                    """
                    insert into public.notes (client_id, animal_id, note_date, title, veterinarian, body, source)
                    values (%s,%s,%s,%s,%s,%s,'manual')
                    """,
                    (client["id"], animal["id"], dados.get("data") or None, dados.get("descricao"), dados.get("veterinario"), dados.get("observacao")),
                )
        conn.commit()


def _consulta_document_path(consulta_id):
    return f"consultas/{consulta_id}/consulta.pdf"


def _ensure_consulta_document(cur, consulta_row, consultation_id):
    file_name = f"consulta-{consultation_id}.pdf"
    storage_path = _consulta_document_path(consultation_id)
    metadata = {
        "type": "consulta_pdf",
        "generated": True,
        "consultation_id": str(consultation_id),
    }
    cur.execute(
        """
        select id
          from public.documents
         where consultation_id = %s
         order by created_at desc
         limit 1
        """,
        (consultation_id,),
    )
    existing = cur.fetchone()
    if existing:
        cur.execute(
            """
            update public.documents
               set client_id = %s,
                   animal_id = %s,
                   file_name = %s,
                   mime_type = %s,
                   storage_path = %s,
                   source_url = %s,
                   caption = %s,
                   metadata = %s,
                   source = %s,
                   updated_at = now()
             where id = %s
            """,
            (
                consulta_row.get("client_id"),
                consulta_row.get("animal_id"),
                file_name,
                "application/pdf",
                storage_path,
                None,
                "PDF da consulta",
                Json(metadata, dumps=_json_dumps),
                consulta_row.get("source") or "manual",
                existing["id"],
            ),
        )
        return str(existing["id"])

    cur.execute(
        """
        insert into public.documents
          (client_id, animal_id, consultation_id, file_name, mime_type, storage_path, source_url, caption, metadata, source)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        returning id
        """,
        (
            consulta_row.get("client_id"),
            consulta_row.get("animal_id"),
            consultation_id,
            file_name,
            "application/pdf",
            storage_path,
            None,
            "PDF da consulta",
            Json(metadata, dumps=_json_dumps),
            consulta_row.get("source") or "manual",
        ),
    )
    row = cur.fetchone()
    return str(row["id"]) if row else None


def _consulta_payload_from_dados(dados, status=None, completed_at=None, completed_by=None):
    payload = {
        "consultation_date": dados.get("consultation_date") or dados.get("data_da_consulta") or dados.get("data") or "",
        "is_return": bool(_parse_bool(dados.get("is_return") if "is_return" in dados else dados.get("is_retorno"))),
        "return_date": dados.get("return_date") or dados.get("data_retorno") or "",
        "status": status or dados.get("status") or "draft",
        "chief_complaint": dados.get("chief_complaint") or dados.get("queixa_principal") or "",
        "anamnesis": dados.get("anamnesis") or dados.get("anamnese") or "",
        "digestive_system": dados.get("digestive_system") or dados.get("sistema_digestorio") or "",
        "cardiorespiratory_system": dados.get("cardiorespiratory_system") or dados.get("sistema_cardiorrespiratorio") or "",
        "genitourinary_system": dados.get("genitourinary_system") or dados.get("sistema_genito_urinario") or "",
        "nervous_musculoskeletal_system": dados.get("nervous_musculoskeletal_system") or dados.get("sistema_nervoso_locomotor") or "",
        "central_temperature": dados.get("central_temperature") or dados.get("temperatura_central") or "",
        "peripheral_temperature": dados.get("peripheral_temperature") or dados.get("temperatura_periferica") or "",
        "heart_rate": dados.get("heart_rate") or dados.get("freq_cardiaca") or "",
        "respiratory_rate": dados.get("respiratory_rate") or dados.get("freq_respiratoria") or "",
        "tpc": dados.get("tpc") or "",
        "lymph_nodes": dados.get("lymph_nodes") or dados.get("linfonodos") or "",
        "mucosa": dados.get("mucosa") or "",
        "hydration": dados.get("hydration") or dados.get("hidratacao") or "",
        "ectoparasites": dados.get("ectoparasites") or "",
        "abdominal_palpation": dados.get("abdominal_palpation") or dados.get("palpacao_abdominal") or "",
        "cardiac_auscultation": dados.get("cardiac_auscultation") or dados.get("ausculta_cardiaca") or "",
        "pulmonary_auscultation": dados.get("pulmonary_auscultation") or dados.get("ausculta_pulmonar") or "",
        "blood_pressure": dados.get("blood_pressure") or dados.get("pressao_arterial") or "",
        "glycemia": dados.get("glycemia") or dados.get("glicemia") or "",
        "delta": dados.get("delta") or "",
        "weight": dados.get("weight") or dados.get("peso") or "",
        "clinical_suspicion": dados.get("clinical_suspicion") or dados.get("suspeita_clinica") or "",
        "requested_exams": dados.get("requested_exams") or dados.get("exames_solicitados") or "",
        "diagnosis": dados.get("diagnosis") or dados.get("diagnostico") or "",
        "outpatient_treatment": dados.get("outpatient_treatment") or dados.get("tratamento_ambulatorial") or "",
        "integumentary_system": dados.get("integumentary_system") or dados.get("sistema_tegumentares_anexos") or "",
        "previous_diseases_treatments": dados.get("previous_diseases_treatments") or dados.get("doencas_tratamentos_anteriores") or "",
        "observations": dados.get("observations") or dados.get("observacoes") or "",
        "veterinarian": dados.get("veterinarian") or dados.get("veterinario") or "",
        "crmv": dados.get("crmv") or "",
        "notes": dados.get("observations") or dados.get("observacoes") or dados.get("chief_complaint") or dados.get("queixa_principal") or "",
        "completed_at": completed_at,
        "completed_by": completed_by or "",
        "source_payload": dict(dados),
    }
    return payload


def salvar_consulta(dados):
    if not _pg_enabled():
        # fallback simples: grava como registro genérico e devolve id textual
        inserir_registro({
            "tipo": "consulta",
            "id_cliente": dados.get("id_cliente"),
            "id_animal": dados.get("id_animal"),
            "data": dados.get("consultation_date") or dados.get("data_da_consulta") or dados.get("data") or "",
            "descricao": dados.get("chief_complaint") or dados.get("queixa_principal") or "Consulta",
            "veterinario": dados.get("veterinarian") or dados.get("veterinario") or "",
            "observacao": dados.get("observations") or dados.get("observacoes") or "",
            "arquivo": "",
        })
        return dados.get("id") or ""

    client = _resolve_client_pg(dados.get("id_cliente"))
    animal = _resolve_animal_pg(dados.get("id_animal"))
    if not client:
        raise ValueError("Cliente não encontrado para salvar consulta.")
    if not animal and dados.get("id_animal"):
        raise ValueError("Animal não encontrado para salvar consulta.")

    consulta_id = dados.get("id")
    consulta_id = str(consulta_id).replace("new_", "") if consulta_id else None
    status = (dados.get("status") or "draft").lower()
    if dados.get("acao") == "finalizar":
        status = "done"
    elif dados.get("acao") == "cancelar":
        status = "cancelled"
    completed_at = None
    completed_by = dados.get("completed_by") or ""
    if status in {"done", "cancelled"}:
        from datetime import datetime
        completed_at = dados.get("completed_at") or datetime.utcnow()

    payload = _consulta_payload_from_dados(dados, status=status, completed_at=completed_at, completed_by=completed_by)
    payload["source"] = dados.get("source") or "manual"
    payload["client_id"] = client["id"]
    payload["animal_id"] = animal["id"] if animal else None
    payload["legacy_consultation_id"] = dados.get("legacy_consultation_id") or dados.get("id_legacy") or None

    campos = (
        "client_id", "animal_id", "consultation_date", "is_return", "return_date",
        "start_time", "end_time", "duration_minutes", "veterinarian", "crmv",
        "status", "chief_complaint", "anamnesis", "digestive_system", "cardiorespiratory_system",
        "genitourinary_system", "nervous_musculoskeletal_system", "central_temperature",
        "peripheral_temperature", "heart_rate", "respiratory_rate", "tpc", "lymph_nodes",
        "mucosa", "hydration", "ectoparasites", "abdominal_palpation", "cardiac_auscultation",
        "pulmonary_auscultation", "blood_pressure", "glycemia", "delta", "weight",
        "clinical_suspicion", "requested_exams", "diagnosis", "outpatient_treatment",
        "integumentary_system", "previous_diseases_treatments", "observations", "notes",
        "completed_at", "completed_by", "source", "source_payload"
    )

    consultation_values = (
        client["id"],
        animal["id"] if animal else None,
        _parse_date(dados.get("consultation_date") or dados.get("data_da_consulta") or dados.get("data")),
        bool(_parse_bool(dados.get("is_return") if "is_return" in dados else dados.get("is_retorno"))),
        _parse_date(dados.get("return_date") or dados.get("data_retorno")),
        dados.get("start_time") or None,
        dados.get("end_time") or None,
        dados.get("duration_minutes") or None,
        dados.get("veterinarian") or dados.get("veterinario") or "",
        dados.get("crmv") or "",
        status,
        dados.get("chief_complaint") or dados.get("queixa_principal") or "",
        dados.get("anamnesis") or dados.get("anamnese") or "",
        dados.get("digestive_system") or dados.get("sistema_digestorio") or "",
        dados.get("cardiorespiratory_system") or dados.get("sistema_cardiorrespiratorio") or "",
        dados.get("genitourinary_system") or dados.get("sistema_genito_urinario") or "",
        dados.get("nervous_musculoskeletal_system") or dados.get("sistema_nervoso_locomotor") or "",
        dados.get("central_temperature") or dados.get("temperatura_central") or "",
        dados.get("peripheral_temperature") or dados.get("temperatura_periferica") or "",
        dados.get("heart_rate") or dados.get("freq_cardiaca") or "",
        dados.get("respiratory_rate") or dados.get("freq_respiratoria") or "",
        dados.get("tpc") or "",
        dados.get("lymph_nodes") or dados.get("linfonodos") or "",
        dados.get("mucosa") or "",
        dados.get("hydration") or dados.get("hidratacao") or "",
        dados.get("ectoparasites") or "",
        dados.get("abdominal_palpation") or dados.get("palpacao_abdominal") or "",
        dados.get("cardiac_auscultation") or dados.get("ausculta_cardiaca") or "",
        dados.get("pulmonary_auscultation") or dados.get("ausculta_pulmonar") or "",
        dados.get("blood_pressure") or dados.get("pressao_arterial") or "",
        dados.get("glycemia") or dados.get("glicemia") or "",
        dados.get("delta") or "",
        dados.get("weight") or dados.get("peso") or "",
        dados.get("clinical_suspicion") or dados.get("suspeita_clinica") or "",
        dados.get("requested_exams") or dados.get("exames_solicitados") or "",
        dados.get("diagnosis") or dados.get("diagnostico") or "",
        dados.get("outpatient_treatment") or dados.get("tratamento_ambulatorial") or "",
        dados.get("integumentary_system") or dados.get("sistema_tegumentares_anexos") or "",
        dados.get("previous_diseases_treatments") or dados.get("doencas_tratamentos_anteriores") or "",
        dados.get("observations") or dados.get("observacoes") or "",
        dados.get("observations") or dados.get("observacoes") or dados.get("chief_complaint") or dados.get("queixa_principal") or "",
        completed_at,
        completed_by,
        dados.get("source") or "manual",
        Json(payload, dumps=_json_dumps),
    )

    with _pg_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if consulta_id:
                placeholders = ", ".join([f"{campo} = %s" for campo in campos])
                cur.execute(
                    f"""
                    update public.consultations
                       set {placeholders},
                           updated_at = now()
                     where id::text = %s
                 returning id
                    """,
                    consultation_values + (consulta_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise ValueError("Consulta não encontrada para atualização.")
                consultation_id = row["id"]
            else:
                cur.execute(
                    f"""
                    insert into public.consultations ({", ".join(campos)})
                    values ({", ".join(["%s"] * len(campos))})
                 returning id
                    """,
                    consultation_values,
                )
                consultation_id = cur.fetchone()["id"]

            _ensure_consulta_document(cur, {"client_id": client["id"], "animal_id": animal["id"] if animal else None, "source": dados.get("source") or "manual"}, consultation_id)
        conn.commit()
    return str(consultation_id)


def get_consulta(consulta_id):
    if not _pg_enabled():
        return None
    row = _resolve_consultation_row(consulta_id)
    if not row:
        return None
    consulta = _map_consultation_row(row)
    client = _map_client_row(_resolve_client_pg(row["client_id"]))
    animal = _map_animal_row(_resolve_animal_pg(row["animal_id"])) if row.get("animal_id") else {}
    consulta.update({
        "cliente": client or {},
        "animal": animal or {},
        "nome_cliente": client.get("nome") if client else "",
        "cpf": client.get("cpf") if client else "",
        "celular": client.get("celular") if client else "",
        "endereco": client.get("endereco") if client else "",
        "cidade": client.get("cidade") if client else "",
        "bairro": client.get("bairro") if client else "",
        "estado": client.get("estado") if client else "",
        "cep": client.get("cep") if client else "",
        "nome_animal": animal.get("nome_animal") if animal else "",
        "especie": animal.get("especie") if animal else "",
        "raca": animal.get("raca") if animal else "",
        "sexo": animal.get("sexo") if animal else "",
        "pelagem": animal.get("pelagem") if animal else "",
        "nascimento": animal.get("nascimento") if animal else "",
        "castrado": animal.get("castrado_label") if animal else "",
        "veterinario": row.get("veterinarian") or "",
    })
    return consulta


def get_consultas_animal(id_cliente, id_animal):
    if not _pg_enabled():
        return _LEGACY_get_registros_animal(id_cliente, id_animal, "consultas")
    client = _resolve_client_pg(id_cliente)
    animal = _resolve_animal_pg(id_animal)
    if not client:
        return _LEGACY_get_registros_animal(id_cliente, id_animal, "consultas")
    rows = _pg_fetchall(
        """
        select *
          from public.consultations
         where client_id = %s
           and (%s::uuid is null or animal_id = %s::uuid)
         order by consultation_date desc, created_at desc
        """,
        (client["id"], animal["id"] if animal else None, animal["id"] if animal else None),
    )
    consultas = []
    for row in rows:
        consulta = _map_consultation_row(row)
        consultas.append({
            "id": consulta["id"],
            "data": consulta["data_da_consulta"],
            "descricao": consulta["queixa_principal"] or consulta["diagnostico"] or "Consulta",
            "veterinario": consulta["veterinario"],
            "observacao": consulta["observacoes"],
            "status": consulta["status"],
            "retorno": "Sim" if consulta["is_retorno"] else "Não",
            "retorno_data": consulta["data_retorno"],
        })
    return consultas


def _consulta_pdf_context(consulta_id):
    consulta = get_consulta(consulta_id)
    if not consulta:
        return None
    client = consulta.get("cliente") or {}
    animal = consulta.get("animal") or {}
    return consulta, client, animal


def get_servicos():
    if not _pg_enabled():
        return _LEGACY_get_servicos()
    rows = _pg_fetchall(
        """
        select name, price, service_type
          from public.services
         where active = true
         order by lower(name)
        """
    )
    if not rows:
        return _LEGACY_get_servicos()
    return [{"nome": r["name"], "valor": f'{float(r["price"]):.2f}'.replace(".", ","), "tipo": r["service_type"]} for r in rows]


def proximo_id_ticket():
    if not _pg_enabled():
        return _LEGACY_proximo_id_ticket()
    row = _pg_fetchone("select count(*) as n from public.tickets")
    return int(row["n"]) + 1 if row else 1


def salvar_ticket(ticket):
    if not _pg_enabled():
        return _LEGACY_salvar_ticket(ticket)
    client = _resolve_client_pg(ticket.get("id_cliente"))
    animal = _resolve_animal_pg(ticket.get("id_animal"))
    if not client:
        raise ValueError("Cliente não encontrado para salvar ticket.")
    items = ticket.get("itens", [])
    subtotal_services = _parse_valor(ticket.get("total_servicos"))
    subtotal_products = _parse_valor(ticket.get("total_produtos"))
    discount_total = _parse_valor(ticket.get("total_descontos"))
    gross_total = _parse_valor(ticket.get("total_bruto"))
    net_total = _parse_valor(ticket.get("total_liquido"))
    from datetime import datetime
    ticket_date = ticket.get("data")
    ticket_date = datetime.strptime(ticket_date, "%d/%m/%Y").date() if ticket_date else date.today()

    with _pg_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                insert into public.tickets
                  (client_id, animal_id, ticket_date, veterinarian, status,
                   subtotal_services, subtotal_products, discount_total, gross_total,
                   net_total, payment_method, notes, source, source_payload)
                values
                  (%s,%s,%s,%s,'paid',%s,%s,%s,%s,%s,%s,%s,'manual',%s)
                returning id
                """,
                (
                    client["id"],
                    animal["id"] if animal else None,
                    ticket_date,
                    ticket.get("veterinario"),
                    subtotal_services,
                    subtotal_products,
                    discount_total,
                    gross_total,
                    net_total,
                    ticket.get("payment_method"),
                    ticket.get("observacao"),
                    Json(ticket, dumps=_json_dumps) if Json else json.dumps(ticket, ensure_ascii=False, default=str),
                ),
            )
            ticket_id = cur.fetchone()["id"]

            for item in items:
                cur.execute(
                    """
                    insert into public.ticket_items
                      (ticket_id, description, item_type, quantity, unit_price, discount, subtotal, source, source_payload)
                    values (%s,%s,%s,%s,%s,%s,%s,'manual',%s)
                    """,
                    (
                        ticket_id,
                        item.get("descricao"),
                        item.get("tipo") or "clinica",
                        int(item.get("qtd") or 1),
                        _parse_valor(item.get("valor")),
                        _parse_valor(item.get("desconto")),
                        _parse_valor(item.get("subtotal")),
                        Json(item, dumps=_json_dumps) if Json else json.dumps(item, ensure_ascii=False, default=str),
                    ),
                )
        conn.commit()
    return str(ticket_id)


def get_ticket(ticket_id):
    if not _pg_enabled():
        return _LEGACY_get_ticket(ticket_id)
    ticket = _resolve_ticket_row(ticket_id)
    if not ticket:
        return _LEGACY_get_ticket(ticket_id)
    client = _map_client_row(_resolve_client_pg(ticket["client_id"]))
    animal = _map_animal_row(_resolve_animal_pg(ticket["animal_id"])) if ticket.get("animal_id") else {}
    items = _pg_fetchall(
        "select description, item_type, quantity, unit_price, discount, subtotal, source_payload from public.ticket_items where ticket_id = %s order by created_at",
        (ticket["id"],),
    )
    return {
        "id": str(ticket["id"]),
        "data": ticket["ticket_date"].strftime("%d/%m/%Y") if ticket.get("ticket_date") else "",
        "veterinario": ticket.get("veterinarian") or "",
        "id_cliente": client.get("id_cliente") if client else str(ticket["client_id"]),
        "id_animal": animal.get("id_animal") if animal else (str(ticket["animal_id"]) if ticket.get("animal_id") else ""),
        "nome_cliente": client.get("nome") if client else "",
        "cpf": client.get("cpf") if client else "",
        "celular": client.get("celular") if client else "",
        "email": client.get("email") if client else "",
        "endereco": client.get("endereco") if client else "",
        "cidade": client.get("cidade") if client else "",
        "nome_animal": animal.get("nome_animal") if animal else "",
        "especie": animal.get("especie") if animal else "",
        "raca": animal.get("raca") if animal else "",
        "pelagem": animal.get("pelagem") if animal else "",
        "nascimento": animal.get("nascimento") if animal else "",
        "sexo": animal.get("sexo") if animal else "",
        "chip": animal.get("chip") if animal else "",
        "itens": [
            {
                "descricao": i.get("description"),
                "tipo": i.get("item_type"),
                "qtd": i.get("quantity"),
                "valor": f'{float(i.get("unit_price") or 0):.2f}'.replace(".", ","),
                "desconto": f'{float(i.get("discount") or 0):.2f}'.replace(".", ","),
                "subtotal": f'{float(i.get("subtotal") or 0):.2f}'.replace(".", ","),
            }
            for i in items
        ],
        "total_servicos": f'{float(ticket.get("subtotal_services") or 0):.2f}'.replace(".", ","),
        "total_produtos": f'{float(ticket.get("subtotal_products") or 0):.2f}'.replace(".", ","),
        "total_bruto": f'{float(ticket.get("gross_total") or 0):.2f}'.replace(".", ","),
        "total_descontos": f'{float(ticket.get("discount_total") or 0):.2f}'.replace(".", ","),
        "total_liquido": f'{float(ticket.get("net_total") or 0):.2f}'.replace(".", ","),
    }


def get_tickets_cliente(id_cliente):
    if not _pg_enabled():
        return _LEGACY_get_tickets_cliente(id_cliente)
    client = _resolve_client_pg(id_cliente)
    if not client:
        return _LEGACY_get_tickets_cliente(id_cliente)
    rows = _pg_fetchall(
        """
        select *
          from public.tickets
         where client_id = %s
         order by ticket_date desc, created_at desc
        """,
        (client["id"],),
    )
    tickets = []
    for r in rows:
        animal_row = _resolve_animal_pg(r["animal_id"]) if r.get("animal_id") else None
        tickets.append({
            "id": str(r["id"]),
            "data": r["ticket_date"].strftime("%d/%m/%Y") if r.get("ticket_date") else "",
            "veterinario": r.get("veterinarian") or "",
            "nome_cliente": client.get("name") or "",
            "nome_animal": (animal_row.get("name") if animal_row else "") or "",
            "animal": (animal_row.get("name") if animal_row else "") or "",
            "total_liquido": f'{float(r.get("net_total") or 0):.2f}'.replace(".", ","),
            "status": r.get("status") or "",
            "pago": (r.get("status") or "").lower() == "paid",
            "numero": str(r["id"]),
            "origem": "postgres",
        })
    return [], tickets


def salvar_receita(dados):
    if not _pg_enabled():
        return _LEGACY_salvar_receita(dados)
    client = _resolve_client_pg(dados.get("id_cliente"))
    animal = _resolve_animal_pg(dados.get("id_animal"))
    if not client:
        raise ValueError("Cliente não encontrado para salvar receita.")
    from datetime import datetime
    prescribed_at = dados.get("data")
    prescribed_at = datetime.strptime(prescribed_at, "%d/%m/%Y").date() if prescribed_at else date.today()
    with _pg_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                insert into public.prescriptions
                  (client_id, animal_id, prescription_type, prescribed_at, veterinarian, crmv, notes, source, source_payload)
                values (%s,%s,%s,%s,%s,%s,%s,'manual',%s)
                returning id
                """,
                (
                    client["id"],
                    animal["id"] if animal else None,
                    dados.get("tipo") or "simple",
                    prescribed_at,
                    dados.get("veterinario"),
                    dados.get("crmv"),
                    dados.get("observacao"),
                    Json(dados, dumps=_json_dumps) if Json else json.dumps(dados, ensure_ascii=False, default=str),
                ),
            )
            prescription_id = str(cur.fetchone()["id"])
            oral = [l.strip() for l in (dados.get("uso_oral") or "").splitlines() if l.strip()]
            topico = [l.strip() for l in (dados.get("uso_topico") or "").splitlines() if l.strip()]
            seq = 1
            for line in oral:
                cur.execute(
                    """
                    insert into public.prescription_items
                      (prescription_id, category, sequence, medication, quantity, instructions, raw_text, source)
                    values (%s,'oral',%s,%s,%s,%s,%s,'manual')
                    """,
                    (prescription_id, seq, line, None, None, line),
                )
                seq += 1
            seq = 1
            for line in topico:
                cur.execute(
                    """
                    insert into public.prescription_items
                      (prescription_id, category, sequence, medication, quantity, instructions, raw_text, source)
                    values (%s,'topical',%s,%s,%s,%s,%s,'manual')
                    """,
                    (prescription_id, seq, line, None, None, line),
                )
                seq += 1
        conn.commit()
    return prescription_id


def get_receita(receita_id):
    if not _pg_enabled():
        return _LEGACY_get_receita(receita_id)
    receita = _resolve_receita_row(receita_id)
    if not receita:
        return _LEGACY_get_receita(receita_id)
    client = _map_client_row(_resolve_client_pg(receita["client_id"]))
    animal = _map_animal_row(_resolve_animal_pg(receita["animal_id"])) if receita.get("animal_id") else {}
    items = _pg_fetchall(
        "select category, medication, quantity, instructions, raw_text from public.prescription_items where prescription_id = %s order by category, sequence",
        (receita["id"],),
    )
    oral = [i.get("raw_text") or i.get("medication") for i in items if i.get("category") == "oral"]
    topico = [i.get("raw_text") or i.get("medication") for i in items if i.get("category") == "topical"]
    return {
        "id": str(receita["id"]),
        "id_cliente": client.get("id_cliente") if client else str(receita["client_id"]),
        "id_animal": animal.get("id_animal") if animal else (str(receita["animal_id"]) if receita.get("animal_id") else ""),
        "tipo": receita.get("prescription_type") or "simple",
        "data": receita["prescribed_at"].strftime("%d/%m/%Y") if receita.get("prescribed_at") else "",
        "veterinario": receita.get("veterinarian") or "",
        "crmv": receita.get("crmv") or "",
        "uso_oral": "\n".join(oral),
        "uso_topico": "\n".join(topico),
        "observacao": receita.get("notes") or "",
        "oral_itens": oral,
        "topico_itens": topico,
    }


def get_receitas_animal(id_cliente, id_animal):
    if not _pg_enabled():
        return _LEGACY_get_receitas_animal(id_cliente, id_animal)
    client = _resolve_client_pg(id_cliente)
    animal = _resolve_animal_pg(id_animal)
    if not client:
        return _LEGACY_get_receitas_animal(id_cliente, id_animal)
    rows = _pg_fetchall(
        """
        select *
          from public.prescriptions
         where client_id = %s
           and (%s::uuid is null or animal_id = %s::uuid)
         order by prescribed_at desc, created_at desc
        """,
        (client["id"], animal["id"] if animal else None, animal["id"] if animal else None),
    )
    return [get_receita(r["id"]) for r in rows]


def resumo_financeiro():
    if not _pg_enabled():
        return _LEGACY_resumo_financeiro()
    rows = _pg_fetchall(
        """
        select ticket_date, net_total, status
          from public.tickets
         order by ticket_date asc
        """
    )
    total_geral = sum(float(r.get("net_total") or 0) for r in rows)
    total_recebido = sum(float(r.get("net_total") or 0) for r in rows if (r.get("status") or "").lower() == "paid")
    total_pendente = total_geral - total_recebido
    qtd_tickets = len(rows)
    qtd_pagos = sum(1 for r in rows if (r.get("status") or "").lower() == "paid")
    from collections import OrderedDict
    import datetime as _dt
    hoje = _dt.date.today()
    meses = OrderedDict()
    for i in range(11, -1, -1):
        ano = hoje.year
        mes = hoje.month - i
        while mes <= 0:
            mes += 12
            ano -= 1
        meses[(ano, mes)] = 0.0
    for r in rows:
        dt = r.get("ticket_date")
        if dt and (dt.year, dt.month) in meses and (r.get("status") or "").lower() == "paid":
            meses[(dt.year, dt.month)] += float(r.get("net_total") or 0)
    nomes_mes = ["", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    fluxo = [{"label": f"{nomes_mes[m]}/{str(a)[2:]}", "valor": round(v, 2)} for (a, m), v in meses.items()]
    return {
        "total_geral": round(total_geral, 2),
        "total_recebido": round(total_recebido, 2),
        "total_pendente": round(total_pendente, 2),
        "qtd_tickets": qtd_tickets,
        "qtd_pagos": qtd_pagos,
        "qtd_pendentes": qtd_tickets - qtd_pagos,
        "fluxo": fluxo,
        "fluxo_max": max((f["valor"] for f in fluxo), default=0) or 1,
    }


def ultimos_tickets(limite=15):
    if not _pg_enabled():
        return _LEGACY_ultimos_tickets(limite=limite)
    rows = _pg_fetchall(
        """
        select t.*, c.name as client_name, a.name as animal_name
          from public.tickets t
          join public.clients c on c.id = t.client_id
     left join public.animals a on a.id = t.animal_id
         order by t.ticket_date desc, t.created_at desc
         limit %s
        """,
        (limite,),
    )
    return [
        {
            "id": str(r["id"]),
            "data": r["ticket_date"].strftime("%d/%m/%Y") if r.get("ticket_date") else "",
            "valor": float(r.get("net_total") or 0),
            "pago": (r.get("status") or "").lower() == "paid",
            "status": r.get("status") or "",
            "cliente": r.get("client_name") or "",
            "animal": r.get("animal_name") or "",
            "numero": str(r["id"]),
            "id_cliente": str(r["client_id"]),
            "origem": "postgres",
        }
        for r in rows
    ]
