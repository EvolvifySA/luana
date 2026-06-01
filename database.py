"""
Inicializa o banco SQLite e importa os CSVs gerados pelo scraper.
Execute database.py diretamente para reimportar: python database.py
"""

import sqlite3
import csv
import os
import re

import config

DB_PATH = "nuvemvet.db"

# Mapeamento CSV → nome da tabela
CSVS = {
    "clientes":        "clientes.csv",
    "clientes_cadastro": "clientes_cadastro.csv",
    "clientes_extra":  "clientes_completo.csv",
    "clientes_raw":    "clientes_completo_raw.csv",
    "animais":         "animais.csv",
    "consultas":       "consultas.csv",
    "vacinas":         "vacinas.csv",
    "receituario":     "receituario.csv",
    "exames":          "exames.csv",
    "cirurgias":       "cirurgias.csv",
    "pesagens":        "pesagens.csv",
    "anotacoes":       "anotacoes.csv",
    "retorno_vacinas": "retorno_vacinas.csv",
}


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def col_safe(name):
    """Converte nome de coluna para identificador SQLite válido."""
    name = name.strip()
    name = re.sub(r"[^\w\s]", "", name, flags=re.UNICODE)
    name = re.sub(r"\s+", "_", name)
    name = name.lower()
    return name or "col"


def dedup_colunas(colunas):
    """Garante que não há nomes de coluna duplicados adicionando sufixo numérico."""
    vistos = {}
    resultado = []
    for c in colunas:
        if c not in vistos:
            vistos[c] = 0
            resultado.append(c)
        else:
            vistos[c] += 1
            resultado.append(f"{c}_{vistos[c]}")
    return resultado


def detectar_delimitador(caminho):
    """Detecta se o CSV usa vírgula ou ponto-e-vírgula."""
    with open(caminho, encoding="utf-8-sig") as f:
        amostra = f.read(4096)
    try:
        dialect = csv.Sniffer().sniff(amostra, delimiters=",;\t")
        return dialect.delimiter
    except Exception:
        # Conta manualmente
        virgulas    = amostra.count(",")
        pvirg       = amostra.count(";")
        return ";" if pvirg > virgulas else ","


def importar_csv(conn, tabela, caminho):
    """Importa um CSV para uma tabela SQLite, criando a tabela se necessário."""
    if not os.path.exists(caminho):
        return 0

    delim = detectar_delimitador(caminho)

    with open(caminho, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=delim)
        if reader.fieldnames is None:
            return 0

        colunas_orig  = list(reader.fieldnames)
        colunas_safe  = dedup_colunas([col_safe(c) for c in colunas_orig])
        print(f"    [{tabela}] colunas: {colunas_safe}")

        # Cria tabela
        defs = ", ".join(f'"{c}" TEXT' for c in colunas_safe)
        conn.execute(f'CREATE TABLE IF NOT EXISTS "{tabela}" (id INTEGER PRIMARY KEY AUTOINCREMENT, {defs})')

        placeholders = ", ".join("?" for _ in colunas_safe)
        col_list     = ", ".join(f'"{c}"' for c in colunas_safe)
        sql          = f'INSERT INTO "{tabela}" ({col_list}) VALUES ({placeholders})'

        linhas = 0
        for row in reader:
            valores = [row.get(orig, "") for orig in colunas_orig]
            conn.execute(sql, valores)
            linhas += 1

    print(f"  {tabela}: {linhas} linhas")
    return linhas


def init_db(force=False):
    """
    Cria o banco e importa os CSVs.
    Se force=True, apaga e recria do zero.
    """
    if force and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print("Banco removido, recriando...")

    if os.path.exists(DB_PATH) and not force:
        return  # já existe

    print("Inicializando banco de dados...")
    conn = get_db()

    for tabela, arquivo in CSVS.items():
        caminho = os.path.join(config.OUTPUT_DIR, arquivo)
        importar_csv(conn, tabela, caminho)

    # Tabela de clientes cadastrados via sistema (novos)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clientes_novos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            nome        TEXT NOT NULL,
            cpf         TEXT,
            celular     TEXT,
            telefone    TEXT,
            email       TEXT,
            endereco    TEXT,
            cidade      TEXT,
            nascimento  TEXT,
            observacao  TEXT,
            criado_em   TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # Tabela de animais cadastrados via sistema
    conn.execute("""
        CREATE TABLE IF NOT EXISTS animais_novos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            id_cliente  TEXT,
            nome        TEXT NOT NULL,
            especie     TEXT,
            raca        TEXT,
            sexo        TEXT,
            nascimento  TEXT,
            pelagem     TEXT,
            chip        TEXT,
            observacao  TEXT,
            criado_em   TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # Registros médicos adicionados via sistema
    conn.execute("""
        CREATE TABLE IF NOT EXISTS registros_novos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo        TEXT NOT NULL,  -- consulta | vacina | exame | cirurgia | receituario
            id_cliente  TEXT,
            id_animal   TEXT,
            data        TEXT,
            descricao   TEXT,
            veterinario TEXT,
            observacao  TEXT,
            arquivo     TEXT,
            criado_em   TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    conn.commit()
    conn.close()
    print("✓ Banco pronto!")


# ─── CONSULTAS ────────────────────────────────────────────────────────────────

def _colunas_tabela(conn, tabela):
    """Retorna lista de nomes de colunas de uma tabela."""
    try:
        rows = conn.execute(f'PRAGMA table_info("{tabela}")').fetchall()
        return [r[1] for r in rows]
    except Exception:
        return []


def buscar_clientes(q="", limite=100, offset=0):
    """
    Busca clientes por nome.
    Usa a tabela 'clientes' (id_cliente + nome corretos) como base,
    e enriquece com dados extras de 'clientes_raw' / 'clientes_extra'.
    """
    conn = get_db()

    # Tabela base — sempre tem id_cliente e nome corretos
    if q:
        base = conn.execute(
            'SELECT id_cliente, nome FROM clientes WHERE nome LIKE ? LIMIT ? OFFSET ?',
            (f"%{q}%", limite, offset)
        ).fetchall()
    else:
        base = conn.execute(
            'SELECT id_cliente, nome FROM clientes LIMIT ? OFFSET ?',
            (limite, offset)
        ).fetchall()

    # Monta dict de dados extras indexado por id_cliente e por nome
    extras_por_id   = {}
    extras_por_nome = {}
    for tabela_extra in ("clientes_cadastro", "clientes_raw", "clientes_extra"):
        cols = _colunas_tabela(conn, tabela_extra)
        if not cols:
            continue
        # Tenta identificar coluna de id (pode ter vários nomes)
        id_col   = next((c for c in cols if c in ("id_cliente", "col", "#")), None)
        nome_col = next((c for c in cols if c == "nome"), None)
        try:
            for row in conn.execute(f'SELECT * FROM "{tabela_extra}"').fetchall():
                d = dict(row)
                if id_col:
                    cid = str(d.get(id_col, "")).strip()
                    if cid and cid not in extras_por_id:
                        extras_por_id[cid] = d
                if nome_col:
                    nm = str(d.get(nome_col, "")).strip().lower()
                    if nm and nm not in extras_por_nome:
                        extras_por_nome[nm] = d
        except Exception:
            continue
        if extras_por_id or extras_por_nome:
            break

    # Junta base + extras (tenta por ID, fallback por nome)
    resultado = []
    for row in base:
        d = {"id_cliente": row["id_cliente"], "nome": row["nome"]}
        extra = (extras_por_id.get(str(row["id_cliente"]).strip()) or
                 extras_por_nome.get(str(row["nome"]).strip().lower()))
        if extra:
            d["cpf"]      = extra.get("cpf", "")
            d["celular"]  = extra.get("celular", "")
            d["endereco"] = extra.get("endereco", "") or extra.get("endereço", "")
            d["cadastro"] = extra.get("cadastro", "")
        resultado.append(d)

    # Clientes cadastrados manualmente
    novos = conn.execute(
        'SELECT id AS id_cliente, nome, cpf, celular FROM clientes_novos WHERE nome LIKE ? LIMIT ?',
        (f"%{q}%", limite)
    ).fetchall()

    conn.close()
    return resultado + [dict(r) for r in novos]


def total_clientes():
    conn = get_db()
    for tabela in ("clientes_raw", "clientes_extra", "clientes"):
        try:
            n = conn.execute(f'SELECT COUNT(*) FROM "{tabela}"').fetchone()[0]
            if n:
                conn.close()
                return n
        except Exception:
            continue
    conn.close()
    return 0


def get_cliente(id_cliente):
    """Retorna dados de um cliente pelo id."""
    conn = get_db()
    cliente = None
    for tabela in ("clientes_raw", "clientes_extra", "clientes"):
        try:
            row = conn.execute(
                f'SELECT * FROM "{tabela}" WHERE id_cliente = ? OR "#" = ? OR "id" = ?',
                (str(id_cliente), str(id_cliente), str(id_cliente))
            ).fetchone()
            if row:
                cliente = dict(row)
                break
        except Exception:
            continue

    if not cliente:
        row = conn.execute(
            'SELECT * FROM clientes_novos WHERE id = ?', (id_cliente,)
        ).fetchone()
        if row:
            cliente = dict(row)

    conn.close()
    return cliente


def get_animais_cliente(id_cliente):
    """Retorna todos os animais de um cliente."""
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM animais WHERE id_cliente = ?', (str(id_cliente),)
    ).fetchall()
    novos = conn.execute(
        'SELECT * FROM animais_novos WHERE id_cliente = ?', (str(id_cliente),)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows] + [dict(r) for r in novos]


def get_registros_animal(id_cliente, id_animal, tipo):
    """Retorna registros de uma seção (consultas, vacinas, etc.) de um animal."""
    conn = get_db()
    tabela = tipo  # mesmo nome da tabela
    registros = []
    try:
        rows = conn.execute(
            f'SELECT * FROM "{tabela}" WHERE id_cliente = ? AND id_animal = ?',
            (str(id_cliente), str(id_animal))
        ).fetchall()
        registros = [dict(r) for r in rows]
    except Exception:
        pass

    # Registros adicionados manualmente
    novos = conn.execute(
        'SELECT * FROM registros_novos WHERE tipo = ? AND id_cliente = ? AND id_animal = ?',
        (tipo.rstrip("s"), str(id_cliente), str(id_animal))
    ).fetchall()
    registros += [dict(r) for r in novos]
    conn.close()
    return registros


def total_animais():
    conn = get_db()
    try:
        n = conn.execute('SELECT COUNT(*) FROM animais').fetchone()[0]
        conn.close()
        return n
    except Exception:
        conn.close()
        return 0


def total_registros(tabela):
    conn = get_db()
    try:
        n = conn.execute(f'SELECT COUNT(*) FROM "{tabela}"').fetchone()[0]
        conn.close()
        return n
    except Exception:
        conn.close()
        return 0


# ─── INSERÇÕES ────────────────────────────────────────────────────────────────

def inserir_cliente(dados):
    conn = get_db()
    conn.execute(
        """INSERT INTO clientes_novos (nome, cpf, celular, telefone, email, endereco, cidade, nascimento, observacao)
           VALUES (:nome, :cpf, :celular, :telefone, :email, :endereco, :cidade, :nascimento, :observacao)""",
        dados,
    )
    conn.commit()
    id_novo = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return id_novo


def inserir_animal(dados):
    conn = get_db()
    conn.execute(
        """INSERT INTO animais_novos (id_cliente, nome, especie, raca, sexo, nascimento, pelagem, chip, observacao)
           VALUES (:id_cliente, :nome, :especie, :raca, :sexo, :nascimento, :pelagem, :chip, :observacao)""",
        dados,
    )
    conn.commit()
    id_novo = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return id_novo


def inserir_registro(dados):
    conn = get_db()
    conn.execute(
        """INSERT INTO registros_novos (tipo, id_cliente, id_animal, data, descricao, veterinario, observacao, arquivo)
           VALUES (:tipo, :id_cliente, :id_animal, :data, :descricao, :veterinario, :observacao, :arquivo)""",
        dados,
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db(force=True)
