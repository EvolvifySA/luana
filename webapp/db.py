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

import requests

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

    resultado = animais + [dict(r) for r in novos]
    for animal in resultado:
        animal["idade"] = animal.get("idade") or _idade_texto(animal.get("nascimento"))
    return resultado


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
        (secao, str(id_cliente), str(id_animal))
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
    nascimento = _normalizar_nascimento_animal(dados) or dados.get("nascimento") or None
    conn.execute(
        """INSERT INTO animais_novos
           (id_cliente,nome,especie,raca,sexo,nascimento,pelagem,chip,observacao)
           VALUES (:id_cliente,:nome,:especie,:raca,:sexo,:nascimento,:pelagem,:chip,:observacao)""",
        {**dados, "nascimento": nascimento},
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


def atualizar_receita(receita_id, dados):
    conn = _get_novos_db()
    _init_receitas_table(conn)
    conn.execute("""
        UPDATE receitas
           SET tipo=:tipo, data=:data, veterinario=:veterinario, crmv=:crmv,
               uso_oral=:uso_oral, uso_topico=:uso_topico, observacao=:observacao
         WHERE id=:id
    """, {**dados, "id": receita_id})
    conn.commit()
    conn.close()
    log.info(f"Receita atualizada: id={receita_id}")
    return receita_id


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


def _birth_date_from_age_fields(dados):
    """Calcula uma data de nascimento a partir de anos/meses/dias informados."""
    from datetime import date as _date, timedelta as _timedelta
    import calendar as _calendar

    def _int_value(chave):
        bruto = (dados.get(chave) or "").strip()
        if not bruto:
            return 0
        try:
            return max(0, int(bruto))
        except ValueError:
            return 0

    anos = _int_value("idade_anos")
    meses = _int_value("idade_meses")
    dias = _int_value("idade_dias")
    if anos <= 0 and meses <= 0 and dias <= 0:
        return None

    hoje = _date.today()

    try:
        nascimento = hoje.replace(year=hoje.year - anos)
    except ValueError:
        # 29/02 cai em 28/02 em anos não bissextos.
        nascimento = hoje.replace(year=hoje.year - anos, day=28)

    total_meses = nascimento.year * 12 + nascimento.month - 1 - meses
    ano = total_meses // 12
    mes = total_meses % 12 + 1
    dia = min(nascimento.day, _calendar.monthrange(ano, mes)[1])
    nascimento = nascimento.replace(year=ano, month=mes, day=dia)
    nascimento = nascimento - _timedelta(days=dias)
    return nascimento


def _normalizar_nascimento_animal(dados):
    """Retorna `birth_date` em ISO a partir de data exata ou idade aproximada."""
    modo = (dados.get("idade_modo") or "").strip().lower()
    if modo == "aproximada":
        nascimento = _birth_date_from_age_fields(dados)
        if nascimento:
            return nascimento.isoformat()
        # Se o formulário veio em modo aproximado mas sem valores válidos,
        # não sobrescrevemos silenciosamente com a data antiga.
        return None

    nascimento = _parse_date(dados.get("nascimento"))
    if nascimento:
        return nascimento.isoformat()

    # Fallback: quando o modo não veio explícito, ainda aceitamos campos de idade.
    nascimento = _birth_date_from_age_fields(dados)
    return nascimento.isoformat() if nascimento else None


def _idade_texto(nascimento):
    """Formata a idade atual como 'X anos Y meses'."""
    from datetime import date as _date

    if not nascimento:
        return ""
    if isinstance(nascimento, _date):
        nasc = nascimento
    else:
        nasc = _parse_date(nascimento)
        if not nasc:
            return ""
    hoje = _date.today()
    anos = hoje.year - nasc.year - ((hoje.month, hoje.day) < (nasc.month, nasc.day))
    meses = hoje.month - nasc.month
    if hoje.day < nasc.day:
        meses -= 1
    meses %= 12
    if anos < 0:
        anos = 0
    return f"{anos} anos {meses} meses"


def _parse_data(texto):
    """Extrai (ano, mes) de uma data DD/MM/AAAA ou DD-MM-AAAA. Retorna None se falhar."""
    if not texto:
        return None
    m = re.search(r"(\d{2})[/-](\d{2})[/-](\d{4})", str(texto))
    if m:
        return (int(m.group(3)), int(m.group(2)))
    return None


def _data_para_iso(texto):
    """Converte uma data (DD/MM/AAAA, DD-MM-AAAA ou já ISO) para 'AAAA-MM-DD'. None se falhar."""
    if not texto:
        return None
    s = str(texto).strip()
    m = re.search(r"(\d{2})[/-](\d{2})[/-](\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def _no_periodo(texto, inicio=None, fim=None):
    """True se a data (texto) está dentro de [inicio, fim] (strings ISO 'AAAA-MM-DD')."""
    if not inicio and not fim:
        return True
    iso = _data_para_iso(texto)
    if not iso:
        return False
    if inicio and iso < inicio:
        return False
    if fim and iso > fim:
        return False
    return True


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


def resumo_financeiro(inicio=None, fim=None):
    """Retorna métricas agregadas para o dashboard financeiro (totais filtrados por período)."""
    todos = _todos_tickets()
    tickets = [t for t in todos if _no_periodo(t["data"], inicio, fim)]

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

    for t in todos:
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


def ultimos_tickets(limite=15, inicio=None, fim=None):
    """Retorna os tickets mais recentes (por data) para a tabela do dashboard."""
    tickets = [t for t in _todos_tickets() if _no_periodo(t["data"], inicio, fim)]

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
_LEGACY_atualizar_receita = atualizar_receita
_LEGACY_resumo_financeiro = resumo_financeiro
_LEGACY_ultimos_tickets = ultimos_tickets

try:
    import json
    import socket
    import threading
    import uuid as _uuid_mod
    from urllib.parse import urlsplit, parse_qs, unquote
    import psycopg2
    from psycopg2.extras import RealDictCursor, Json
    from psycopg2 import pool as _pg_pool_mod
except Exception:  # pragma: no cover - fallback when psycopg2 is unavailable
    psycopg2 = None
    RealDictCursor = None
    Json = None
    _pg_pool_mod = None
    threading = None


def _json_dumps(value):
    return json.dumps(value, ensure_ascii=False, default=str)


def _pg_enabled():
    return bool(getattr(config, "DATABASE_URL", "").strip()) and psycopg2 is not None


# ─── Pool de conexões / conexão por requisição ───────────────────────────────
#
# Antes, cada query abria uma conexão psycopg2 nova (DNS + TCP + TLS + auth) ao
# Supabase remoto e a descartava. Uma única página chegava a abrir dezenas de
# conexões (N+1), o que dominava o tempo de resposta. Agora mantemos um pool por
# processo e reaproveitamos UMA conexão por requisição HTTP (guardada em flask.g),
# devolvendo-a ao pool no teardown.

_PG_POOL = None
_PG_POOL_LOCK = threading.Lock() if threading is not None else None

# Timeouts e keepalives evitam que um connect/query pendure por minutos quando a
# rede ou o pooler do Supabase engasga (causa dos outliers de lentidão extrema).
_PG_CONNECT_OPTS = {
    "connect_timeout": 5,
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
    "options": "-c statement_timeout=15000",
}


def _pg_connect_args():
    """Resolve os argumentos de conexão a partir do DATABASE_URL (uma vez)."""
    dsn = getattr(config, "DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("DATABASE_URL não configurado.")

    parsed = urlsplit(dsn)
    if parsed.hostname:
        host = parsed.hostname
        port = parsed.port or 5432
        kwargs = dict(
            dbname=parsed.path.lstrip("/") or "postgres",
            user=unquote(parsed.username or ""),
            password=unquote(parsed.password or ""),
            host=host,
            port=port,
            sslmode=(parse_qs(parsed.query).get("sslmode") or ["require"])[0],
            **_PG_CONNECT_OPTS,
        )
        # Força IPv4 (o host direto do Supabase é IPv6-only em alguns ambientes).
        try:
            for family, _, _, _, sockaddr in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM):
                if family == socket.AF_INET:
                    kwargs["hostaddr"] = sockaddr[0]
                    break
        except socket.gaierror:
            pass
        return ((), kwargs)

    return ((dsn,), dict(_PG_CONNECT_OPTS))


def _pg_pool_size():
    try:
        return max(1, int(getattr(config, "PG_POOL_MAX", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _get_pool():
    global _PG_POOL
    if _PG_POOL is not None:
        return _PG_POOL
    if _pg_pool_mod is None or _PG_POOL_LOCK is None:
        return None
    with _PG_POOL_LOCK:
        if _PG_POOL is None:
            args, kwargs = _pg_connect_args()
            maxconn = _pg_pool_size() or 8
            _PG_POOL = _pg_pool_mod.ThreadedConnectionPool(1, maxconn, *args, **kwargs)
    return _PG_POOL


def _has_app_ctx():
    try:
        from flask import has_app_context
        return has_app_context()
    except Exception:
        return False


class _PgConnCtx:
    """Context manager que preserva a semântica de `with _pg_conn() as conn:`
    (commit no sucesso, rollback no erro), mas reaproveita a conexão da
    requisição em vez de abrir/fechar uma nova a cada query."""

    def __init__(self, conn, release):
        self._conn = conn
        self._release = release

    def __enter__(self):
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            if self._release is not None:
                self._release(self._conn)
        return False


def _pg_conn():
    pool = _get_pool()

    # Dentro de uma requisição: reaproveita uma única conexão por requisição.
    if pool is not None and _has_app_ctx():
        from flask import g
        conn = getattr(g, "_pg_conn", None)
        if conn is None or conn.closed:
            conn = pool.getconn()
            g._pg_conn = conn
        return _PgConnCtx(conn, release=None)

    # Fora de requisição (scripts): empresta e devolve ao pool no fim do bloco.
    if pool is not None:
        conn = pool.getconn()
        return _PgConnCtx(conn, release=pool.putconn)

    # Sem pool disponível: conexão direta (fallback).
    args, kwargs = _pg_connect_args()
    conn = psycopg2.connect(*args, **kwargs)
    return _PgConnCtx(conn, release=lambda c: c.close())


def _pg_teardown(exc=None):
    """Devolve a conexão da requisição ao pool (registrar no teardown_appcontext)."""
    try:
        from flask import g
    except Exception:
        return
    conn = g.pop("_pg_conn", None)
    if conn is None:
        return
    pool = _PG_POOL
    try:
        if getattr(conn, "closed", True):
            if pool is not None:
                pool.putconn(conn, close=True)
            return
        try:
            conn.rollback()
        except Exception:
            pass
        if pool is not None:
            pool.putconn(conn)
        else:
            conn.close()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


def init_app(app):
    """Liga o ciclo de vida da conexão por requisição ao app Flask."""
    app.teardown_appcontext(_pg_teardown)


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
        "numero": row.get("number") or "",
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
    birth_date = row.get("birth_date")
    return {
        "id_animal": str(row["id"]),
        "id_cliente": str(row["client_id"]),
        "nome": row.get("name") or "",
        "nome_animal": row.get("name") or "",
        "especie": row.get("species") or "",
        "raca": row.get("breed") or "",
        "sexo": row.get("sex") or "",
        "nascimento": birth_date.isoformat() if hasattr(birth_date, "isoformat") else (birth_date or ""),
        "idade": _idade_texto(birth_date.isoformat() if hasattr(birth_date, "isoformat") else (birth_date or "")),
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


def _uuid_or_none(value):
    """Retorna o UUID canônico se `value` for um UUID válido, senão None."""
    try:
        return str(_uuid_mod.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None


def _request_cache(namespace):
    """Cache por requisição (flask.g) para evitar re-resolver o mesmo registro
    várias vezes na mesma página. Fora de requisição, retorna None (sem cache)."""
    if not _has_app_ctx():
        return None
    from flask import g
    store = getattr(g, "_resolve_cache", None)
    if store is None:
        store = {}
        g._resolve_cache = store
    return store.setdefault(namespace, {})


def _resolve_client_pg(id_cliente):
    clean = str(id_cliente).replace("new_", "")
    cache = _request_cache("client")
    if cache is not None and clean in cache:
        return cache[clean]

    as_uuid = _uuid_or_none(clean)
    if as_uuid:
        # Caminho rápido: usa a chave primária (índice), sem seq scan.
        row = _pg_fetchone(
            "select * from public.clients where id = %s::uuid limit 1",
            (as_uuid,),
        )
    else:
        row = _pg_fetchone(
            """
            select *
              from public.clients
             where legacy_client_id = %s
                or name = %s
             limit 1
            """,
            (clean, clean),
        )
    if cache is not None:
        cache[clean] = row
    return row


def _resolve_animal_pg(id_animal):
    clean = str(id_animal).replace("new_", "")
    cache = _request_cache("animal")
    if cache is not None and clean in cache:
        return cache[clean]

    as_uuid = _uuid_or_none(clean)
    if as_uuid:
        row = _pg_fetchone(
            "select * from public.animals where id = %s::uuid limit 1",
            (as_uuid,),
        )
    else:
        row = _pg_fetchone(
            """
            select *
              from public.animals
             where legacy_animal_id = %s
             limit 1
            """,
            (clean,),
        )
    if cache is not None:
        cache[clean] = row
    return row


def _resolve_ticket_row(ticket_id):
    return _pg_fetchone("select * from public.tickets where id::text = %s limit 1", (str(ticket_id),))


def _resolve_receita_row(receita_id):
    return _pg_fetchone("select * from public.prescriptions where id::text = %s limit 1", (str(receita_id),))


def _resolve_consultation_row(consulta_id):
    return _pg_fetchone("select * from public.consultations where id::text = %s limit 1", (str(consulta_id),))


def _default_admin_email():
    # Reaproveita o e-mail já configurado da clínica como mailbox padrão.
    return getattr(config, "DEFAULT_ADMIN_EMAIL", "") or config.CLINICA.get("email") or ""


def _supabase_auth_url(path):
    base = (getattr(config, "SUPABASE_URL", "") or "").rstrip("/")
    if not base:
        raise RuntimeError("SUPABASE_URL não configurado.")
    return f"{base}{path}"


def _supabase_auth_request(method, path, *, json_data=None, params=None, bearer=None, timeout=25):
    api_key = (getattr(config, "SUPABASE_SERVICE_ROLE_KEY", "") or "").strip()
    if not api_key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY não configurado.")
    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {bearer or api_key}",
        "Accept": "application/json",
    }
    if json_data is not None:
        headers["Content-Type"] = "application/json"
    resp = requests.request(
        method.upper(),
        _supabase_auth_url(path),
        headers=headers,
        json=json_data,
        params=params,
        timeout=timeout,
    )
    return resp


def _pg_usuario_por_username(username):
    return _pg_fetchone(
        """
        select id, username, full_name, password_hash, email, auth_user_id, active
          from public.users
         where lower(username) = lower(%s)
         limit 1
        """,
        (username.strip(),),
    )


def _pg_usuario_por_id(user_id):
    return _pg_fetchone(
        """
        select id, username, full_name, password_hash, email, auth_user_id, active
          from public.users
         where id::text = %s
            or auth_user_id::text = %s
         limit 1
        """,
        (str(user_id), str(user_id)),
    )


def _pg_usuario_por_email(email):
    return _pg_fetchone(
        """
        select id, username, full_name, password_hash, email, auth_user_id, active
          from public.users
         where lower(email) = lower(%s)
         limit 1
        """,
        (email.strip(),),
    )


def _pg_auth_user_por_email(email):
    return _pg_fetchone(
        """
        select id::text as id, email, created_at, email_confirmed_at
          from auth.users
         where lower(email) = lower(%s)
         limit 1
        """,
        (email.strip(),),
    )


def _sincronizar_public_user_auth(row, auth_user_id=None):
    if not row:
        return
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update public.users
                   set email = coalesce(nullif(email, ''), %s),
                       auth_user_id = coalesce(auth_user_id, %s::uuid),
                       updated_at = now()
                 where id = %s
                """,
                (_default_admin_email(), auth_user_id, row["id"]),
            )
        conn.commit()


def _auth_usuario_ensure(row, senha_padrao=None):
    if not row:
        return None
    email = (row.get("email") or "").strip()
    if not email:
        email = _default_admin_email()
    if not email:
        raise RuntimeError("Nenhum e-mail configurado para o usuário.")

    auth_user = _pg_auth_user_por_email(email)
    if auth_user:
        _sincronizar_public_user_auth(row, auth_user.get("id"))
        return auth_user

    senha = senha_padrao or "evolvify2026"
    resp = _supabase_auth_request(
        "POST",
        "/auth/v1/admin/users",
        json_data={
            "email": email,
            "password": senha,
            "email_confirm": True,
            "user_metadata": {
                "full_name": row.get("full_name") or row.get("username") or "",
                "username": row.get("username") or "",
            },
        },
    )
    if resp.status_code not in (200, 201):
        # Se já existir um usuário no Auth mas a criação falhou, tenta recuperar pelo e-mail.
        fallback = _pg_auth_user_por_email(email)
        if fallback:
            _sincronizar_public_user_auth(row, fallback.get("id"))
            return fallback
        raise RuntimeError(_extract_supabase_error(resp))

    payload = resp.json() if resp.content else {}
    auth_user = payload.get("user") or payload.get("data", {}).get("user") or {}
    auth_id = auth_user.get("id")
    _sincronizar_public_user_auth(row, auth_id)
    return auth_user


def _extract_supabase_error(resp):
    try:
        data = resp.json()
        return data.get("msg") or data.get("error_description") or data.get("error") or resp.text
    except Exception:
        return resp.text or f"Erro HTTP {resp.status_code}"


def garantir_usuario_padrao():
    if not _pg_enabled():
        return _LEGACY_garantir_usuario_padrao()
    from werkzeug.security import generate_password_hash

    default_email = _default_admin_email()
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from public.users")
            total = cur.fetchone()[0]
            if total == 0:
                cur.execute(
                    """
                    insert into public.users (username, password_hash, full_name, role, active, email)
                    values (%s, %s, %s, %s, true, %s)
                    """,
                    ("luana", generate_password_hash("evolvify2026"), "Luana Feitosa", "admin", default_email or None),
                )
                conn.commit()
                row = _pg_usuario_por_username("luana")
                if row:
                    _auth_usuario_ensure(row, "evolvify2026")
                return ("luana", "evolvify2026")

    row = _pg_usuario_por_username("luana")
    if row and (not row.get("email")) and default_email:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update public.users set email = %s, updated_at = now() where id = %s",
                    (default_email, row["id"]),
                )
            conn.commit()
        row["email"] = default_email
    if row and row.get("email") and not row.get("auth_user_id"):
        _auth_usuario_ensure(row, "evolvify2026")
    return None


def verificar_login(username, senha):
    if not _pg_enabled():
        return _LEGACY_verificar_login(username, senha)
    row = _pg_usuario_por_username(username)
    if not row:
        return None
    if not row.get("active", True):
        return None
    if not row.get("email"):
        return None

    resp = _supabase_auth_request(
        "POST",
        "/auth/v1/token",
        params={"grant_type": "password"},
        json_data={"email": row["email"], "password": senha},
    )
    if resp.status_code != 200:
        return None

    payload = resp.json() if resp.content else {}
    auth_user = payload.get("user") or {}
    _sincronizar_public_user_auth(row, auth_user.get("id"))
    return {
        "id": row["id"],
        "username": row["username"],
        "nome": row.get("full_name") or row["username"],
        "email": row.get("email") or "",
        "auth_user_id": auth_user.get("id") or row.get("auth_user_id") or "",
        "auth_access_token": payload.get("access_token") or "",
        "auth_refresh_token": payload.get("refresh_token") or "",
    }


def trocar_senha(user_id, senha_nova, access_token=None):
    if not _pg_enabled():
        return _LEGACY_trocar_senha(user_id, senha_nova)
    from werkzeug.security import generate_password_hash

    row = _pg_usuario_por_id(user_id)
    if not row:
        raise ValueError("Usuário não encontrado.")
    if not access_token:
        raise ValueError("Sessão Supabase ausente para alterar a senha.")

    resp = _supabase_auth_request(
        "PUT",
        "/auth/v1/user",
        bearer=access_token,
        json_data={"password": senha_nova},
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(_extract_supabase_error(resp))

    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update public.users
                   set password_hash = %s,
                       updated_at = now()
                 where id::text = %s
                """,
                (generate_password_hash(senha_nova), str(user_id)),
            )
        conn.commit()


def solicitar_reset_senha(username, redirect_to):
    if not _pg_enabled():
        raise RuntimeError("Redefinição de senha disponível apenas com Supabase Auth.")
    row = _pg_usuario_por_username(username)
    if not row:
        raise ValueError("Usuário não encontrado.")
    email = (row.get("email") or "").strip()
    if not email:
        raise ValueError("Este usuário ainda não possui e-mail configurado.")

    resp = _supabase_auth_request(
        "POST",
        "/auth/v1/recover",
        json_data={"email": email, "redirect_to": redirect_to},
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(_extract_supabase_error(resp))
    return email


def confirmar_reset_senha(token_hash, senha_nova, tipo="recovery"):
    if not _pg_enabled():
        raise RuntimeError("Redefinição de senha disponível apenas com Supabase Auth.")
    resp = _supabase_auth_request(
        "POST",
        "/auth/v1/verify",
        json_data={"token_hash": token_hash, "type": tipo},
    )
    if resp.status_code != 200:
        raise RuntimeError(_extract_supabase_error(resp))
    payload = resp.json() if resp.content else {}
    session_data = payload.get("session") or payload
    access_token = session_data.get("access_token") or payload.get("access_token")
    if not access_token:
        raise RuntimeError("Não foi possível obter a sessão Supabase para redefinir a senha.")
    user = session_data.get("user") or payload.get("user") or {}
    user_id = user.get("id")
    if not user_id:
        raise RuntimeError("Usuário autenticado não identificado.")
    trocar_senha(user_id, senha_nova, access_token=access_token)
    return user_id


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
    rows, _ = buscar_clientes_paginado(q=q, limite=limite, offset=offset)
    return rows


def buscar_clientes_paginado(q="", limite=50, offset=0):
    """Retorna (clientes, total) com um único round-trip ao Postgres."""
    if not _pg_enabled():
        rows = _LEGACY_buscar_clientes(q=q, limite=limite, offset=offset)
        return rows, _LEGACY_total_clientes()

    where_sql = ""
    params = []
    if q:
        like = f"%{q}%"
        where_sql = """where lower(coalesce(c.name, '')) like lower(%s)
                    or coalesce(c.cpf, '') like %s
                    or exists (select 1 from public.animals a
                                where a.client_id = c.id
                                  and lower(coalesce(a.name, '')) like lower(%s))"""
        params.extend([like, like, like])

    with _pg_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                with filtered as (
                    select c.*, count(*) over() as total_count
                      from public.clients c
                      {where_sql}
                )
                select *
                  from filtered
                 order by lower(name)
                 limit %s offset %s
                """,
                tuple(params + [limite, offset]),
            )
            raw_rows = cur.fetchall()

    total = int(raw_rows[0]["total_count"]) if raw_rows else 0
    rows = [_map_client_row(r) for r in raw_rows]

    return rows, total


def buscar_clientes_com_animais(q="", limite=20, offset=0):
    """Retorna clientes e animais em uma unica ida ao Postgres para atendimento."""
    if not _pg_enabled():
        return [
            {"cliente": c, "animais": _LEGACY_get_animais_cliente(c["id_cliente"])}
            for c in _LEGACY_buscar_clientes(q=q, limite=limite, offset=offset)
        ]

    where_sql = ""
    params = []
    if q:
        where_sql = "where lower(coalesce(c.name, '')) like lower(%s)"
        params.append(f"%{q}%")

    with _pg_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                with filtered as (
                    select c.*
                      from public.clients c
                      {where_sql}
                     order by lower(c.name)
                     limit %s offset %s
                )
                select f.*,
                       coalesce(animais.rows, '[]'::jsonb) as animais
                  from filtered f
                  left join lateral (
                    select jsonb_agg(to_jsonb(a) order by lower(a.name)) as rows
                      from public.animals a
                     where a.client_id = f.id
                  ) animais on true
                 order by lower(f.name)
                """,
                tuple(params + [limite, offset]),
            )
            raw_rows = cur.fetchall()

    achados = []
    for row in raw_rows:
        animais = row.pop("animais") or []
        achados.append({
            "cliente": _map_client_row(row),
            "animais": [_map_animal_row(a) for a in animais],
        })
    return achados


def get_cliente(id_cliente):
    if not _pg_enabled():
        return _LEGACY_get_cliente(id_cliente)
    row = _resolve_client_pg(id_cliente)
    return _map_client_row(row) if row else None


def get_animais_cliente(id_cliente):
    if not _pg_enabled():
        return _LEGACY_get_animais_cliente(id_cliente)
    client = _resolve_client_pg(id_cliente)
    if not client:
        return []
    rows = _pg_fetchall("select * from public.animals where client_id = %s order by lower(name)", (client["id"],))
    animais = [_map_animal_row(r) for r in rows]
    return animais


def get_registros_animal(id_cliente, id_animal, secao):
    if not _pg_enabled():
        return _LEGACY_get_registros_animal(id_cliente, id_animal, secao)
    client = _resolve_client_pg(id_cliente)
    animal = _resolve_animal_pg(id_animal)
    if not client or not animal:
        return []

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


def _data_para_ordenar(valor):
    """Converte 'DD/MM/AAAA' ou 'AAAA-MM-DD' numa data comparável (a mais antiga possível se não der pra ler)."""
    from datetime import date, datetime
    if isinstance(valor, date):
        return valor
    txt = str(valor or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(txt, fmt).date()
        except ValueError:
            continue
    return date.min


def get_peso_atual(id_cliente, id_animal):
    """Peso mais recente do animal (última pesagem), pra usar em receitas/consultas.

    Junta pesagens manuais e as importadas do histórico (csv/Supabase) e pega
    a de data mais recente — não existe um campo fixo de "peso" no cadastro do
    animal, só o histórico de pesagens mesmo.
    """
    registros = get_registros_animal(id_cliente, id_animal, "pesagens")
    melhor_data = None
    peso = ""
    for r in registros:
        bruto = r.get("Peso") or r.get("descricao") or r.get("peso") or ""
        bruto = str(bruto).strip()
        if not bruto:
            continue
        data_ord = _data_para_ordenar(r.get("Data da pesagem") or r.get("data"))
        if melhor_data is None or data_ord > melhor_data:
            melhor_data = data_ord
            peso = bruto
    return peso


def atualizar_status_ticket(ticket_id, status, payment_method=None):
    if not _pg_enabled():
        raise RuntimeError("Atualização de status do ticket disponível apenas no Postgres.")
    status = (status or "").strip().lower()
    if status not in {"paid", "pending", "cancelled", "draft"}:
        raise ValueError("Status inválido para ticket.")
    ticket = _resolve_ticket_row(ticket_id)
    if not ticket:
        raise ValueError("Ticket não encontrado.")
    # Só faz sentido registrar forma de pagamento quando está pago.
    # Ao voltar para pendente/cancelado, limpamos a forma de pagamento.
    metodo = (payment_method or "").strip() or None
    if status != "paid":
        metodo = None
    with _pg_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "update public.tickets set status = %s, payment_method = %s where id = %s returning id",
                (status, metodo, ticket["id"]),
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
                insert into public.clients (name, cpf, mobile, phone, email, address, number, city, neighborhood, state, zip_code, birth_date, notes, source)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'manual')
                returning id
                """,
                (
                    dados.get("nome"),
                    dados.get("cpf"),
                    dados.get("celular"),
                    dados.get("telefone"),
                    dados.get("email"),
                    dados.get("endereco"),
                    dados.get("numero"),
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


def atualizar_cliente(id_cliente, dados):
    """Atualiza os dados de um cliente existente (apenas Supabase)."""
    if not _pg_enabled():
        raise ValueError("A edição de cliente só está disponível no banco Supabase.")
    client = _resolve_client_pg(id_cliente)
    if not client:
        raise ValueError("Cliente não encontrado.")
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update public.clients set
                    name = %s, cpf = %s, mobile = %s, phone = %s, email = %s,
                    address = %s, number = %s, city = %s, neighborhood = %s, state = %s,
                    zip_code = %s, birth_date = %s, notes = %s
                where id = %s
                """,
                (
                    dados.get("nome"),
                    dados.get("cpf"),
                    dados.get("celular"),
                    dados.get("telefone"),
                    dados.get("email"),
                    dados.get("endereco"),
                    dados.get("numero"),
                    dados.get("cidade"),
                    dados.get("bairro"),
                    dados.get("estado"),
                    dados.get("cep") or dados.get("zip_code"),
                    dados.get("nascimento") or None,
                    dados.get("observacao"),
                    client["id"],
                ),
            )
        conn.commit()
    return str(client["id"])


def inserir_animal(dados):
    if not _pg_enabled():
        return _LEGACY_inserir_animal(dados)
    client = _resolve_client_pg(dados.get("id_cliente"))
    if not client:
        raise ValueError("Cliente não encontrado para inserir animal.")
    nascimento = _normalizar_nascimento_animal(dados) or dados.get("nascimento") or None
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
                    nascimento,
                    dados.get("pelagem"),
                    dados.get("chip"),
                    _parse_bool(dados.get("castrado")),
                    dados.get("observacao"),
                ),
            )
            new_id = str(cur.fetchone()["id"])
        conn.commit()
    return new_id


def atualizar_animal(id_animal, dados):
    """Atualiza os dados de um animal existente (apenas Supabase)."""
    if not _pg_enabled():
        raise ValueError("A edição de animal só está disponível no banco Supabase.")
    animal = _resolve_animal_pg(id_animal)
    if not animal:
        raise ValueError("Animal não encontrado.")
    nascimento = _normalizar_nascimento_animal(dados) or dados.get("nascimento") or None
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update public.animals set
                    name = %s, species = %s, breed = %s, sex = %s,
                    birth_date = %s, coat = %s, chip = %s, castrado = %s, notes = %s
                where id = %s
                """,
                (
                    dados.get("nome"),
                    dados.get("especie"),
                    dados.get("raca"),
                    dados.get("sexo"),
                    nascimento,
                    dados.get("pelagem"),
                    dados.get("chip"),
                    _parse_bool(dados.get("castrado")),
                    dados.get("observacao"),
                    animal["id"],
                ),
            )
        conn.commit()
    return str(animal["id"])


def inserir_registro(dados):
    if not _pg_enabled():
        return _LEGACY_inserir_registro(dados)
    client = _resolve_client_pg(dados.get("id_cliente"))
    animal = _resolve_animal_pg(dados.get("id_animal"))
    if not client or not animal:
        raise ValueError("Cliente ou animal não encontrado para registrar histórico.")
    # OBS: "secao" vem exatamente igual à chave usada nas abas do cliente
    # (plural: consultas/vacinas/exames/cirurgias/pesagens) — NÃO tentar
    # "desplularizar" com rstrip('s'): "pesagens" vira "pesagen" (não
    # "pesagem"), o que fazia toda pesagem cair silenciosamente em anotações.
    secao = dados.get("tipo") or ""
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            if secao == "consultas":
                cur.execute(
                    """
                    insert into public.consultations (client_id, animal_id, consultation_date, veterinarian, notes, source)
                    values (%s,%s,%s,%s,%s,'manual')
                    """,
                    (client["id"], animal["id"], dados.get("data") or None, dados.get("veterinario"), dados.get("observacao") or dados.get("descricao")),
                )
            elif secao == "vacinas":
                cur.execute(
                    """
                    insert into public.vaccinations (client_id, animal_id, vaccine_name, applied_at, veterinarian, notes, source)
                    values (%s,%s,%s,%s,%s,%s,'manual')
                    """,
                    (client["id"], animal["id"], dados.get("descricao"), dados.get("data") or None, dados.get("veterinario"), dados.get("observacao")),
                )
            elif secao == "exames":
                cur.execute(
                    """
                    insert into public.exams (client_id, animal_id, exam_date, exam_type, requester, notes, source, source_url, requires_browser)
                    values (%s,%s,%s,%s,%s,%s,'manual',%s,false)
                    """,
                    (client["id"], animal["id"], dados.get("data") or None, dados.get("descricao"), dados.get("veterinario"), dados.get("observacao"), dados.get("arquivo") or None),
                )
            elif secao == "cirurgias":
                cur.execute(
                    """
                    insert into public.surgeries (client_id, animal_id, surgery_date, title, veterinarian, notes, source)
                    values (%s,%s,%s,%s,%s,%s,'manual')
                    """,
                    (client["id"], animal["id"], dados.get("data") or None, dados.get("descricao"), dados.get("veterinario"), dados.get("observacao")),
                )
            elif secao == "pesagens":
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
        return []
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
    # Supabase ainda sem serviços/produtos migrados → usa o catálogo do servicos.csv.
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
        return None
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
        # Supabase ligado: não cair pro CSV. Sem cliente resolvido = sem tickets.
        return [], []
    rows = _pg_fetchall(
        """
        select t.*, a.name as animal_name
          from public.tickets t
     left join public.animals a on a.id = t.animal_id
         where t.client_id = %s
         order by t.ticket_date desc, t.created_at desc
        """,
        (client["id"],),
    )
    tickets = []
    for r in rows:
        nome_animal = r.get("animal_name") or ""
        tickets.append({
            "id": str(r["id"]),
            "data": r["ticket_date"].strftime("%d/%m/%Y") if r.get("ticket_date") else "",
            "veterinario": r.get("veterinarian") or "",
            "nome_cliente": client.get("name") or "",
            "nome_animal": nome_animal,
            "animal": nome_animal,
            "total_liquido": f'{float(r.get("net_total") or 0):.2f}'.replace(".", ","),
            "status": r.get("status") or "",
            "pago": (r.get("status") or "").lower() == "paid",
            "forma_pagamento": r.get("payment_method") or "",
            "numero": str(r["id"]),
            "origem": "postgres",
        })
    return [], tickets


def apagar_cliente(id_cliente):
    """Apaga um cliente e seus prontuários (animais, consultas, vacinas...).

    Proteção: se houver tickets ou receitas no histórico financeiro, a exclusão
    é bloqueada para não perder esses registros.
    """
    if not _pg_enabled():
        raise ValueError("A exclusão de cliente só está disponível no banco Supabase.")
    client = _resolve_client_pg(id_cliente)
    if not client:
        raise ValueError("Cliente não encontrado.")

    n_tk = _pg_fetchone("select count(*) as n from public.tickets where client_id = %s", (client["id"],))
    n_rx = _pg_fetchone("select count(*) as n from public.prescriptions where client_id = %s", (client["id"],))
    if (n_tk and int(n_tk["n"]) > 0) or (n_rx and int(n_rx["n"]) > 0):
        raise ValueError(
            "Este cliente tem tickets e/ou receitas no histórico financeiro e "
            "não pode ser apagado (proteção contra perda de dados)."
        )

    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from public.clients where id = %s", (client["id"],))
        conn.commit()
    return client.get("name") or str(client["id"])


def apagar_ticket(ticket_id):
    """Apaga um ticket e seus itens (ticket_items cai em cascata)."""
    if not _pg_enabled():
        raise ValueError("A exclusão de ticket só está disponível no banco Supabase.")
    row = _resolve_ticket_row(ticket_id)
    if not row:
        raise ValueError("Ticket não encontrado.")
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from public.tickets where id = %s", (row["id"],))
        conn.commit()
    return str(row.get("id"))


def apagar_animal(id_animal):
    """Apaga um animal e seus prontuários (consultas, vacinas etc. em cascata).

    Tickets e receitas são preservados (o vínculo com o animal vira nulo) para
    não perder o histórico financeiro.
    """
    if not _pg_enabled():
        raise ValueError("A exclusão de animal só está disponível no banco Supabase.")
    animal = _resolve_animal_pg(id_animal)
    if not animal:
        raise ValueError("Animal não encontrado.")
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from public.animals where id = %s", (animal["id"],))
        conn.commit()
    return animal.get("name") or str(animal["id"])


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
    # O banco aceita só 'simple' ou 'controlled'; o form manda 'simples'/'especial'.
    tipo_db = "controlled" if (dados.get("tipo") or "").lower() in ("especial", "special", "controlled") else "simple"
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
                    tipo_db,
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


def _build_receita(receita, items, client, animal):
    """Monta o dict de receita a partir de linhas já carregadas (sem novas queries)."""
    oral = [i.get("raw_text") or i.get("medication") for i in items if i.get("category") == "oral"]
    topico = [i.get("raw_text") or i.get("medication") for i in items if i.get("category") == "topical"]
    return {
        "id": str(receita["id"]),
        "id_cliente": client.get("id_cliente") if client else str(receita["client_id"]),
        "id_animal": animal.get("id_animal") if animal else (str(receita["animal_id"]) if receita.get("animal_id") else ""),
        "tipo": "especial" if receita.get("prescription_type") == "controlled" else "simples",
        "data": receita["prescribed_at"].strftime("%d/%m/%Y") if receita.get("prescribed_at") else "",
        "veterinario": receita.get("veterinarian") or "",
        "crmv": receita.get("crmv") or "",
        "uso_oral": "\n".join(oral),
        "uso_topico": "\n".join(topico),
        "observacao": receita.get("notes") or "",
        "oral_itens": oral,
        "topico_itens": topico,
    }


def get_receita(receita_id):
    if not _pg_enabled():
        return _LEGACY_get_receita(receita_id)
    receita = _resolve_receita_row(receita_id)
    if not receita:
        return None
    client = _map_client_row(_resolve_client_pg(receita["client_id"]))
    animal = _map_animal_row(_resolve_animal_pg(receita["animal_id"])) if receita.get("animal_id") else {}
    items = _pg_fetchall(
        "select category, medication, quantity, instructions, raw_text from public.prescription_items where prescription_id = %s order by category, sequence",
        (receita["id"],),
    )
    return _build_receita(receita, items, client, animal)


def get_receitas_animal(id_cliente, id_animal):
    if not _pg_enabled():
        return _LEGACY_get_receitas_animal(id_cliente, id_animal)
    client = _resolve_client_pg(id_cliente)
    animal = _resolve_animal_pg(id_animal)
    if not client:
        return []
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
    if not rows:
        return []

    # Busca TODOS os itens das receitas numa única query (evita N+1).
    presc_ids = [r["id"] for r in rows]
    item_rows = _pg_fetchall(
        """
        select prescription_id, category, medication, quantity, instructions, raw_text
          from public.prescription_items
         where prescription_id = any(%s::uuid[])
         order by category, sequence
        """,
        (presc_ids,),
    )
    itens_por_receita = {}
    for it in item_rows:
        itens_por_receita.setdefault(it["prescription_id"], []).append(it)

    client_map = _map_client_row(client)
    animal_map = _map_animal_row(animal) if animal else {}
    return [
        _build_receita(r, itens_por_receita.get(r["id"], []), client_map, animal_map)
        for r in rows
    ]


def atualizar_receita(receita_id, dados):
    if not _pg_enabled():
        return _LEGACY_atualizar_receita(receita_id, dados)
    receita = _resolve_receita_row(receita_id)
    if not receita:
        raise ValueError("Receita não encontrada.")
    from datetime import datetime
    prescribed_at = dados.get("data")
    prescribed_at = datetime.strptime(prescribed_at, "%d/%m/%Y").date() if prescribed_at else date.today()
    tipo_db = "controlled" if (dados.get("tipo") or "").lower() in ("especial", "special", "controlled") else "simple"
    with _pg_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                update public.prescriptions
                   set prescription_type=%s, prescribed_at=%s, veterinarian=%s, crmv=%s, notes=%s
                 where id=%s
                """,
                (tipo_db, prescribed_at, dados.get("veterinario"), dados.get("crmv"),
                 dados.get("observacao"), receita["id"]),
            )
            cur.execute("delete from public.prescription_items where prescription_id=%s", (receita["id"],))
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
                    (receita["id"], seq, line, None, None, line),
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
                    (receita["id"], seq, line, None, None, line),
                )
                seq += 1
        conn.commit()
    return str(receita["id"])


# ─── Receitas personalizadas (modelos reutilizáveis em qualquer cliente) ──────

def _init_receita_templates_local(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS receita_templates (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            nome        TEXT NOT NULL,
            tipo        TEXT,
            veterinario TEXT,
            crmv        TEXT,
            uso_oral    TEXT,
            uso_topico  TEXT,
            observacao  TEXT,
            criado_em   TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()


def _init_receita_templates_pg():
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                create table if not exists public.prescription_templates (
                    id uuid primary key default gen_random_uuid(),
                    name text not null,
                    prescription_type text default 'simples',
                    veterinarian text,
                    crmv text,
                    uso_oral text,
                    uso_topico text,
                    notes text,
                    created_at timestamptz not null default now()
                )
            """)
        conn.commit()


def salvar_receita_template(nome, dados):
    """Salva uma receita como modelo reutilizável (vale para qualquer cliente)."""
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("Dê um nome para a receita personalizada.")
    if not _pg_enabled():
        conn = _get_novos_db()
        _init_receita_templates_local(conn)
        cur = conn.execute(
            """INSERT INTO receita_templates (nome, tipo, veterinario, crmv, uso_oral, uso_topico, observacao)
               VALUES (?,?,?,?,?,?,?)""",
            (nome, dados.get("tipo"), dados.get("veterinario"), dados.get("crmv"),
             dados.get("uso_oral"), dados.get("uso_topico"), dados.get("observacao")),
        )
        conn.commit()
        new_id = cur.lastrowid
        conn.close()
        return str(new_id)
    _init_receita_templates_pg()
    with _pg_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """insert into public.prescription_templates
                     (name, prescription_type, veterinarian, crmv, uso_oral, uso_topico, notes)
                   values (%s,%s,%s,%s,%s,%s,%s) returning id""",
                (nome, dados.get("tipo"), dados.get("veterinario"), dados.get("crmv"),
                 dados.get("uso_oral"), dados.get("uso_topico"), dados.get("observacao")),
            )
            tid = str(cur.fetchone()["id"])
        conn.commit()
    return tid


def get_receita_templates():
    """Lista todas as receitas personalizadas salvas."""
    if not _pg_enabled():
        conn = _get_novos_db()
        _init_receita_templates_local(conn)
        rows = conn.execute("SELECT * FROM receita_templates ORDER BY nome").fetchall()
        conn.close()
        return [dict(r) for r in rows]
    _init_receita_templates_pg()
    rows = _pg_fetchall("select * from public.prescription_templates order by lower(name)")
    return [{
        "id": str(r["id"]), "nome": r.get("name") or "",
        "tipo": r.get("prescription_type") or "simples",
        "veterinario": r.get("veterinarian") or "", "crmv": r.get("crmv") or "",
        "uso_oral": r.get("uso_oral") or "", "uso_topico": r.get("uso_topico") or "",
        "observacao": r.get("notes") or "",
    } for r in rows]


def get_receita_template(template_id):
    """Retorna uma receita personalizada pelo id (ou None)."""
    if not _pg_enabled():
        conn = _get_novos_db()
        _init_receita_templates_local(conn)
        row = conn.execute("SELECT * FROM receita_templates WHERE id = ?", (str(template_id),)).fetchone()
        conn.close()
        return dict(row) if row else None
    _init_receita_templates_pg()
    r = _pg_fetchone("select * from public.prescription_templates where id::text = %s", (str(template_id),))
    if not r:
        return None
    return {
        "id": str(r["id"]), "nome": r.get("name") or "",
        "tipo": r.get("prescription_type") or "simples",
        "veterinario": r.get("veterinarian") or "", "crmv": r.get("crmv") or "",
        "uso_oral": r.get("uso_oral") or "", "uso_topico": r.get("uso_topico") or "",
        "observacao": r.get("notes") or "",
    }


def atualizar_receita_template(template_id, dados):
    """Atualiza uma receita personalizada existente."""
    nome = (dados.get("nome") or "").strip()
    if not nome:
        raise ValueError("Dê um nome para a receita personalizada.")
    if not _pg_enabled():
        conn = _get_novos_db()
        _init_receita_templates_local(conn)
        conn.execute(
            """UPDATE receita_templates SET nome=?, tipo=?, veterinario=?, crmv=?,
                   uso_oral=?, uso_topico=?, observacao=? WHERE id=?""",
            (nome, dados.get("tipo"), dados.get("veterinario"), dados.get("crmv"),
             dados.get("uso_oral"), dados.get("uso_topico"), dados.get("observacao"), str(template_id)),
        )
        conn.commit()
        conn.close()
        return str(template_id)
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """update public.prescription_templates set
                       name=%s, prescription_type=%s, veterinarian=%s, crmv=%s,
                       uso_oral=%s, uso_topico=%s, notes=%s
                   where id::text = %s""",
                (nome, dados.get("tipo"), dados.get("veterinario"), dados.get("crmv"),
                 dados.get("uso_oral"), dados.get("uso_topico"), dados.get("observacao"), str(template_id)),
            )
        conn.commit()
    return str(template_id)


def apagar_receita_template(template_id):
    """Remove uma receita personalizada (modelo)."""
    if not _pg_enabled():
        conn = _get_novos_db()
        _init_receita_templates_local(conn)
        conn.execute("DELETE FROM receita_templates WHERE id = ?", (str(template_id),))
        conn.commit()
        conn.close()
        return True
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from public.prescription_templates where id::text = %s", (str(template_id),))
        conn.commit()
    return True


def resumo_financeiro(inicio=None, fim=None):
    if not _pg_enabled():
        return _LEGACY_resumo_financeiro(inicio, fim)
    rows = _pg_fetchall(
        """
        select
            coalesce(sum(net_total), 0) as total_geral,
            coalesce(sum(net_total) filter (where lower(status) = 'paid'), 0) as total_recebido,
            count(*) as qtd_tickets,
            count(*) filter (where lower(status) = 'paid') as qtd_pagos
          from public.tickets
         where (%s::date is null or ticket_date >= %s::date)
           and (%s::date is null or ticket_date <= %s::date)
        """,
        (inicio, inicio, fim, fim),
    )
    row = rows[0] if rows else {}
    fluxo_rows = _pg_fetchall(
        """
        with months as (
            select date_trunc('month', current_date) - (interval '1 month' * gs.i) as month_start
              from generate_series(11, 0, -1) as gs(i)
        )
        select
            extract(year from m.month_start)::int as ano,
            extract(month from m.month_start)::int as mes,
            coalesce(sum(t.net_total) filter (where lower(t.status) = 'paid'), 0) as valor
          from months m
     left join public.tickets t
            on date_trunc('month', t.ticket_date) = m.month_start
           and lower(t.status) = 'paid'
         group by m.month_start
         order by m.month_start
        """
    )
    nomes_mes = ["", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    fluxo = [
        {
            "label": f"{nomes_mes[int(r['mes'])]}/{str(int(r['ano']))[2:]}",
            "valor": round(float(r.get("valor") or 0), 2),
            "mes_key": f"{int(r['ano']):04d}-{int(r['mes']):02d}",
        }
        for r in fluxo_rows
    ]
    return {
        "total_geral": round(float(row.get("total_geral") or 0), 2),
        "total_recebido": round(float(row.get("total_recebido") or 0), 2),
        "total_pendente": round(float(row.get("total_geral") or 0) - float(row.get("total_recebido") or 0), 2),
        "qtd_tickets": int(row.get("qtd_tickets") or 0),
        "qtd_pagos": int(row.get("qtd_pagos") or 0),
        "qtd_pendentes": int(row.get("qtd_tickets") or 0) - int(row.get("qtd_pagos") or 0),
        "fluxo": fluxo,
        "fluxo_max": max((f["valor"] for f in fluxo), default=0) or 1,
    }


def ultimos_tickets(limite=15, inicio=None, fim=None):
    if not _pg_enabled():
        return _LEGACY_ultimos_tickets(limite=limite, inicio=inicio, fim=fim)
    rows = _pg_fetchall(
        """
        select t.*, c.name as client_name, a.name as animal_name
          from public.tickets t
          join public.clients c on c.id = t.client_id
     left join public.animals a on a.id = t.animal_id
         where (%s::date is null or t.ticket_date >= %s::date)
           and (%s::date is null or t.ticket_date <= %s::date)
         order by t.ticket_date desc, t.created_at desc
         limit %s
        """,
        (inicio, inicio, fim, fim, limite),
    )
    return [
        {
            "id": str(r["id"]),
            "data": r["ticket_date"].strftime("%d/%m/%Y") if r.get("ticket_date") else "",
            "valor": float(r.get("net_total") or 0),
            "pago": (r.get("status") or "").lower() == "paid",
            "status": r.get("status") or "",
            "forma_pagamento": r.get("payment_method") or "",
            "cliente": r.get("client_name") or "",
            "animal": r.get("animal_name") or "",
            "numero": str(r["id"]),
            "id_cliente": str(r["client_id"]),
            "origem": "postgres",
        }
        for r in rows
    ]


def dashboard_overview(inicio=None, fim=None):
    """Busca os dados do dashboard em poucos round-trips ao banco."""
    if not _pg_enabled():
        stats = {
            "clientes": _LEGACY_total_clientes(),
            "animais": _LEGACY_total_animais(),
            "consultas": _LEGACY_total_registros("consultas"),
            "vacinas": _LEGACY_total_registros("vacinas"),
            "exames": _LEGACY_total_registros("exames"),
        }
        return {
            "stats": stats,
            "fin": _LEGACY_resumo_financeiro(inicio, fim),
            "ultimos": _LEGACY_ultimos_tickets(8, inicio, fim),
        }

    with _pg_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                select
                    (select count(*) from public.clients) as clientes,
                    (select count(*) from public.animals) as animais,
                    (select count(*) from public.consultations) as consultas,
                    (select count(*) from public.vaccinations) as vacinas,
                    (select count(*) from public.exams) as exames
                """
            )
            stats_row = cur.fetchone() or {}

            cur.execute(
                """
                select
                    coalesce(sum(net_total), 0) as total_geral,
                    coalesce(sum(net_total) filter (where lower(status) = 'paid'), 0) as total_recebido,
                    count(*) as qtd_tickets,
                    count(*) filter (where lower(status) = 'paid') as qtd_pagos
                  from public.tickets
                 where (%s::date is null or ticket_date >= %s::date)
                   and (%s::date is null or ticket_date <= %s::date)
                """,
                (inicio, inicio, fim, fim),
            )
            fin_row = cur.fetchone() or {}

            cur.execute(
                """
                with months as (
                    select date_trunc('month', current_date) - (interval '1 month' * gs.i) as month_start
                      from generate_series(11, 0, -1) as gs(i)
                )
                select
                    extract(year from m.month_start)::int as ano,
                    extract(month from m.month_start)::int as mes,
                    coalesce(sum(t.net_total) filter (where lower(t.status) = 'paid'), 0) as valor
                  from months m
             left join public.tickets t
                    on date_trunc('month', t.ticket_date) = m.month_start
                   and lower(t.status) = 'paid'
                 group by m.month_start
                 order by m.month_start
                """
            )
            fluxo_rows = cur.fetchall()

            cur.execute(
                """
                select
                    t.id,
                    t.client_id,
                    t.animal_id,
                    t.ticket_date,
                    t.net_total,
                    t.status,
                    t.created_at,
                    c.name as client_name,
                    a.name as animal_name
                  from public.tickets t
                  join public.clients c on c.id = t.client_id
             left join public.animals a on a.id = t.animal_id
                 where (%s::date is null or t.ticket_date >= %s::date)
                   and (%s::date is null or t.ticket_date <= %s::date)
                 order by t.ticket_date desc, t.created_at desc
                 limit 8
                """,
                (inicio, inicio, fim, fim),
            )
            ultimos_rows = [dict(row) for row in cur.fetchall()]

    nomes_mes = ["", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    fluxo = [
        {
            "label": f"{nomes_mes[int(r['mes'])]}/{str(int(r['ano']))[2:]}",
            "valor": round(float(r.get("valor") or 0), 2),
            "mes_key": f"{int(r['ano']):04d}-{int(r['mes']):02d}",
        }
        for r in fluxo_rows
    ]
    total_geral = float(fin_row.get("total_geral") or 0)
    total_recebido = float(fin_row.get("total_recebido") or 0)
    qtd_tickets = int(fin_row.get("qtd_tickets") or 0)
    qtd_pagos = int(fin_row.get("qtd_pagos") or 0)
    fin = {
        "total_geral": round(total_geral, 2),
        "total_recebido": round(total_recebido, 2),
        "total_pendente": round(total_geral - total_recebido, 2),
        "qtd_tickets": qtd_tickets,
        "qtd_pagos": qtd_pagos,
        "qtd_pendentes": qtd_tickets - qtd_pagos,
        "fluxo": fluxo,
        "fluxo_max": max((f["valor"] for f in fluxo), default=0) or 1,
    }

    ultimos = [
        {
            "id": str(r["id"]),
            "data": r["ticket_date"].strftime("%d/%m/%Y") if r.get("ticket_date") else "",
            "valor": float(r.get("net_total") or 0),
            "pago": (r.get("status") or "").lower() == "paid",
            "status": r.get("status") or "",
            "forma_pagamento": r.get("payment_method") or "",
            "cliente": r.get("client_name") or "",
            "animal": r.get("animal_name") or "",
            "numero": str(r["id"]),
            "id_cliente": str(r["client_id"]),
            "origem": "postgres",
        }
        for r in ultimos_rows
    ]

    return {
        "stats": {
            "clientes": int(stats_row.get("clientes") or 0),
            "animais": int(stats_row.get("animais") or 0),
            "consultas": int(stats_row.get("consultas") or 0),
            "vacinas": int(stats_row.get("vacinas") or 0),
            "exames": int(stats_row.get("exames") or 0),
        },
        "fin": fin,
        "ultimos": ultimos,
    }
