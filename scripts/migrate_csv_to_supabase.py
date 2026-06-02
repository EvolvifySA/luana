"""Migra os CSVs exportados para o schema PostgreSQL do Supabase.

Uso:
  set DATABASE_URL=postgresql://...
  python scripts/migrate_csv_to_supabase.py --dry-run
  python scripts/migrate_csv_to_supabase.py

O script foi desenhado para ser idempotente:
- clientes/animais/serviÃ§os usam upsert por legacy ids ou nome
- registros histÃ³ricos sÃ£o inseridos por lote
- os CSVs ficam como fonte de verdade inicial e continuam preservados
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Iterable, Iterator

import psycopg2
from psycopg2.extras import Json

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "dados_exportados"


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _connect():
    dsn = _env("DATABASE_URL") or _env("SUPABASE_DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL ou SUPABASE_DATABASE_URL nÃ£o definido.")
    return psycopg2.connect(dsn)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _checksum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    value = str(value).strip()
    if not value:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _parse_number(value: str | None) -> float:
    if not value:
        return 0.0
    s = str(value).replace("R$", "").replace(" ", "")
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _json_dumps(value):
    return json.dumps(value, ensure_ascii=False, default=str)


def _slug_source(source: str) -> str:
    if not source:
        return "import"
    return source.strip().lower()


def _batch(cur, source_file: str, entity_name: str, rows: int, imported_by: str = "csv-migration") -> str:
    checksum = None
    source_path = DATA_DIR / source_file
    if source_path.exists():
        checksum = _checksum(source_path)
    cur.execute(
        """
        insert into public.import_batches (source_file, entity_name, checksum, row_count, imported_by)
        values (%s, %s, %s, %s, %s)
        returning id
        """,
        (source_file, entity_name, checksum, rows, imported_by),
    )
    return str(cur.fetchone()[0])


def _insert_import_row(cur, batch_id: str, entity_name: str, legacy_key: str | None, row_number: int | None, raw: dict, normalized: dict, status: str = "ok", error_message: str | None = None):
    cur.execute(
        """
        insert into public.import_rows
          (batch_id, entity_name, legacy_key, row_number, raw_data, normalized_data, status, error_message)
        values (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (batch_id, entity_name, legacy_key, row_number, Json(raw, dumps=_json_dumps), Json(normalized, dumps=_json_dumps), status, error_message),
    )


def _upsert_client(cur, row: dict[str, str], source: str, batch_id: str, row_number: int):
    legacy_client_id = row.get("id_cliente") or None
    name = (row.get("nome") or row.get("#") or row.get("Cliente") or "").strip()
    if not name:
        return None
    normalized = {
        "legacy_client_id": legacy_client_id,
        "name": name,
        "cpf": (row.get("cpf") or row.get("Cadastro") or row.get("CPF") or "").strip() or None,
        "mobile": (row.get("celular") or row.get("CPF") or "").strip() or None,
        "phone": (row.get("telefone") or "").strip() or None,
        "email": (row.get("email") or "").strip() or None,
        "address": (row.get("endereco") or row.get("endereÃ§o") or row.get("Nome") or "").strip() or None,
        "city": (row.get("cidade") or "").strip() or None,
        "zip_code": (row.get("cep") or "").strip() or None,
        "birth_date": _parse_date(row.get("nascimento") or ""),
        "notes": (row.get("observacao") or row.get("observaÃ§Ã£o") or "").strip() or None,
        "source": _slug_source(source),
        "source_payload": row,
    }
    db_values = dict(normalized)
    db_values["source_payload"] = Json(row, dumps=_json_dumps)
    cur.execute(
        """
        insert into public.clients
          (legacy_client_id, name, cpf, mobile, phone, email, address, city, zip_code, birth_date, notes, source, source_payload)
        values (%(legacy_client_id)s, %(name)s, %(cpf)s, %(mobile)s, %(phone)s, %(email)s, %(address)s, %(city)s, %(zip_code)s, %(birth_date)s, %(notes)s, %(source)s, %(source_payload)s)
        on conflict (legacy_client_id)
        do update set
          name = excluded.name,
          cpf = coalesce(excluded.cpf, public.clients.cpf),
          mobile = coalesce(excluded.mobile, public.clients.mobile),
          phone = coalesce(excluded.phone, public.clients.phone),
          email = coalesce(excluded.email, public.clients.email),
          address = coalesce(excluded.address, public.clients.address),
          city = coalesce(excluded.city, public.clients.city),
          zip_code = coalesce(excluded.zip_code, public.clients.zip_code),
          birth_date = coalesce(excluded.birth_date, public.clients.birth_date),
          notes = coalesce(excluded.notes, public.clients.notes),
          source = excluded.source,
          source_payload = excluded.source_payload
        returning id
        """,
        db_values,
    )
    client_id = str(cur.fetchone()[0])
    _insert_import_row(cur, batch_id, "clients", legacy_client_id or name, row_number, row, normalized)
    return client_id


def _upsert_animal(cur, row: dict[str, str], client_id: str, source: str, batch_id: str, row_number: int):
    legacy_animal_id = row.get("id_animal") or None
    name = (row.get("nome_animal") or row.get("nome") or "").strip()
    if not name:
        return None
    normalized = {
        "legacy_animal_id": legacy_animal_id,
        "client_id": client_id,
        "name": name,
        "species": (row.get("especie") or "").strip() or None,
        "breed": (row.get("raca") or "").strip() or None,
        "sex": (row.get("sexo") or "").strip() or None,
        "birth_date": _parse_date(row.get("nascimento") or ""),
        "coat": (row.get("pelagem") or "").strip() or None,
        "chip": (row.get("chip") or "").strip() or None,
        "card_number": (row.get("carteirinha") or "").strip() or None,
        "deceased_at": None if (row.get("obito") or "").strip().lower() in ("", "nÃ£o", "nao") else _parse_date(row.get("obito") or ""),
        "notes": (row.get("observacao") or row.get("observaÃ§Ã£o") or "").strip() or None,
        "source": _slug_source(source),
        "source_payload": row,
    }
    db_values = dict(normalized)
    db_values["source_payload"] = Json(row, dumps=_json_dumps)
    cur.execute(
        """
        insert into public.animals
          (legacy_animal_id, client_id, name, species, breed, sex, birth_date, coat, chip, card_number, deceased_at, notes, source, source_payload)
        values (%(legacy_animal_id)s, %(client_id)s, %(name)s, %(species)s, %(breed)s, %(sex)s, %(birth_date)s, %(coat)s, %(chip)s, %(card_number)s, %(deceased_at)s, %(notes)s, %(source)s, %(source_payload)s)
        on conflict (client_id, legacy_animal_id)
        do update set
          name = excluded.name,
          species = coalesce(excluded.species, public.animals.species),
          breed = coalesce(excluded.breed, public.animals.breed),
          sex = coalesce(excluded.sex, public.animals.sex),
          birth_date = coalesce(excluded.birth_date, public.animals.birth_date),
          coat = coalesce(excluded.coat, public.animals.coat),
          chip = coalesce(excluded.chip, public.animals.chip),
          card_number = coalesce(excluded.card_number, public.animals.card_number),
          deceased_at = coalesce(excluded.deceased_at, public.animals.deceased_at),
          notes = coalesce(excluded.notes, public.animals.notes),
          source = excluded.source,
          source_payload = excluded.source_payload
        returning id
        """,
        db_values,
    )
    animal_id = str(cur.fetchone()[0])
    _insert_import_row(cur, batch_id, "animals", legacy_animal_id or name, row_number, row, normalized)
    return animal_id


def _map_service_type(value: str | None) -> str:
    s = (value or "").strip().lower()
    if s in {"clinica", "clÃ­nica"}:
        return "clinica"
    if s in {"petshop"}:
        return "petshop"
    if s in {"produto", "products"}:
        return "produto"
    if s in {"laboratorio", "laboratÃ³rio"}:
        return "laboratorio"
    return "outro"


def import_clients(cur):
    rows = _read_csv(DATA_DIR / "clientes.csv")
    complete = {r.get("#", "").strip().lower(): r for r in _read_csv(DATA_DIR / "clientes_completo.csv")}
    cadastro = {r.get("id_cliente", "").strip(): r for r in _read_csv(DATA_DIR / "clientes_cadastro.csv")}
    batch_id = _batch(cur, "clientes.csv", "clients", len(rows))
    print(f"[migrate] clients: {len(rows)} linhas")
    client_map = {}
    for i, row in enumerate(rows, 1):
        name_key = (row.get("nome") or "").strip().lower()
        merged = dict(row)
        merged.update(complete.get(name_key, {}))
        merged.update(cadastro.get(row.get("id_cliente", "").strip(), {}))
        client_id = _upsert_client(cur, merged, "csv", batch_id, i)
        if client_id:
            client_map[row.get("id_cliente", "").strip()] = client_id
        if i % 100 == 0 or i == len(rows):
            print(f"[migrate] clients: {i}/{len(rows)}")
    return client_map


def import_animals(cur, client_map: dict[str, str]):
    rows = _read_csv(DATA_DIR / "animais.csv")
    details = {(r.get("id_cliente", "").strip(), r.get("id_animal", "").strip()): r for r in _read_csv(DATA_DIR / "animais_detalhes.csv")}
    batch_id = _batch(cur, "animais.csv", "animals", len(rows))
    print(f"[migrate] animals: {len(rows)} linhas")
    animal_map = {}
    for i, row in enumerate(rows, 1):
        merged = dict(row)
        merged.update(details.get((row.get("id_cliente", "").strip(), row.get("id_animal", "").strip()), {}))
        legacy_client_id = row.get("id_cliente", "").strip()
        client_id = client_map.get(legacy_client_id)
        if not client_id:
            continue
        animal_id = _upsert_animal(cur, merged, client_id, "csv", batch_id, i)
        if animal_id:
            animal_map[(legacy_client_id, row.get("id_animal", "").strip())] = animal_id
        if i % 100 == 0 or i == len(rows):
            print(f"[migrate] animals: {i}/{len(rows)}")
    return animal_map


def import_services(cur):
    rows = _read_csv(DATA_DIR / "servicos.csv")
    if not rows:
        return
    batch_id = _batch(cur, "servicos.csv", "services", len(rows))
    print(f"[migrate] services: {len(rows)} linhas")
    for i, row in enumerate(rows, 1):
        name = (row.get("Nome do ServiÃ§o") or row.get("nome") or "").strip()
        if not name:
            continue
        normalized = {
            "legacy_name": name,
            "name": name,
            "price": _parse_number(row.get("Valor do serviÃ§o") or row.get("valor") or row.get("Valor")),
            "service_type": _map_service_type(row.get("tipo")),
            "active": True,
            "notes": None,
            "source": "csv",
            "source_payload": row,
        }
        db_values = dict(normalized)
        db_values["source_payload"] = Json(row, dumps=_json_dumps)
        cur.execute(
            """
            insert into public.services
              (legacy_name, name, price, service_type, active, notes, source, source_payload)
            values (%(legacy_name)s, %(name)s, %(price)s, %(service_type)s, %(active)s, %(notes)s, %(source)s, %(source_payload)s)
            on conflict (name, service_type)
            do update set
              price = excluded.price,
              active = excluded.active,
              source = excluded.source,
              source_payload = excluded.source_payload
            """,
            db_values,
        )
        _insert_import_row(cur, batch_id, "services", name, i, row, normalized)
        if i % 100 == 0 or i == len(rows):
            print(f"[migrate] services: {i}/{len(rows)}")


def _find_client_id_by_legacy(cur, legacy_client_id: str) -> str | None:
    cur.execute("select id from public.clients where legacy_client_id = %s", (legacy_client_id,))
    row = cur.fetchone()
    return str(row[0]) if row else None


def _find_animal_id_by_legacy(cur, client_id: str, legacy_animal_id: str) -> str | None:
    cur.execute(
        "select id from public.animals where client_id = %s and legacy_animal_id = %s",
        (client_id, legacy_animal_id),
    )
    row = cur.fetchone()
    return str(row[0]) if row else None


def _resolve_ids(cur, client_map: dict[str, str], animal_map: dict[tuple[str, str], str], legacy_client_id: str, legacy_animal_id: str):
    client_id = client_map.get(legacy_client_id) or _find_client_id_by_legacy(cur, legacy_client_id)
    if not client_id:
        return None, None
    animal_id = None
    if legacy_animal_id:
        animal_id = animal_map.get((legacy_client_id, legacy_animal_id)) or _find_animal_id_by_legacy(cur, client_id, legacy_animal_id)
    return client_id, animal_id


def import_tickets(cur, client_map: dict[str, str], animal_map: dict[tuple[str, str], str]):
    rows = _read_csv(DATA_DIR / "tickets.csv")
    if not rows:
        return
    batch_id = _batch(cur, "tickets.csv", "tickets", len(rows))
    print(f"[migrate] tickets: {len(rows)} linhas")
    for i, row in enumerate(rows, 1):
        legacy_client_id = row.get("id_cliente", "").strip()
        legacy_animal_id = row.get("id_animal", "").strip()
        client_id = client_map.get(legacy_client_id) or _find_client_id_by_legacy(cur, legacy_client_id)
        if not client_id:
            continue
        animal_id = animal_map.get((legacy_client_id, legacy_animal_id)) or _find_animal_id_by_legacy(cur, client_id, legacy_animal_id)
        total_liquid = _parse_number(row.get("Valor Final") or row.get("Valor Ticket"))
        status_text = (row.get("Status") or "").strip().lower()
        normalized = {
            "legacy_ticket_id": (row.get("NÂº ticket") or row.get("N ticket") or row.get("id_financeiro") or "").strip() or None,
            "legacy_financeiro_id": (row.get("id_financeiro") or "").strip() or None,
            "client_id": client_id,
            "animal_id": animal_id,
            "ticket_date": _parse_date(row.get("Data") or row.get("Registrado")) or date.today(),
            "veterinarian": None,
            "status": "paid" if "pago" in status_text else "pending" if "pend" in status_text else "draft",
            "subtotal_services": total_liquid,
            "subtotal_products": 0,
            "discount_total": _parse_number(row.get("Desconto")),
            "gross_total": _parse_number(row.get("Valor Ticket") or row.get("Valor Final")),
            "net_total": total_liquid,
            "payment_method": None,
            "notes": None,
            "source": "csv",
            "source_payload": row,
        }
        db_values = dict(normalized)
        db_values["source_payload"] = Json(row, dumps=_json_dumps)
        cur.execute(
            """
            insert into public.tickets
              (legacy_ticket_id, legacy_financeiro_id, client_id, animal_id, ticket_date, veterinarian, status,
               subtotal_services, subtotal_products, discount_total, gross_total, net_total, payment_method, notes, source, source_payload)
            values
              (%(legacy_ticket_id)s, %(legacy_financeiro_id)s, %(client_id)s, %(animal_id)s, %(ticket_date)s, %(veterinarian)s, %(status)s,
               %(subtotal_services)s, %(subtotal_products)s, %(discount_total)s, %(gross_total)s, %(net_total)s, %(payment_method)s, %(notes)s, %(source)s, %(source_payload)s)
            on conflict (legacy_ticket_id)
            do update set
              client_id = excluded.client_id,
              animal_id = excluded.animal_id,
              ticket_date = excluded.ticket_date,
              status = excluded.status,
              subtotal_services = excluded.subtotal_services,
              subtotal_products = excluded.subtotal_products,
              discount_total = excluded.discount_total,
              gross_total = excluded.gross_total,
              net_total = excluded.net_total,
              source = excluded.source,
              source_payload = excluded.source_payload
            returning id
            """,
            db_values,
        )
        if i % 100 == 0 or i == len(rows):
            print(f"[migrate] tickets: {i}/{len(rows)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Executa tudo em uma transaÃ§Ã£o e faz rollback.")
    args = parser.parse_args()

    print("[migrate] conectando ao banco...")
    conn = _connect()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            print("[migrate] importando clientes...")
            client_map = import_clients(cur)
            print("[migrate] importando animais...")
            animal_map = import_animals(cur, client_map)
            print("[migrate] importando serviços...")
            import_services(cur)
            print("[migrate] importando tickets...")
            import_tickets(cur, client_map, animal_map)
            print("[migrate] importando consultas...")
            import_consultations(cur, client_map, animal_map)
            print("[migrate] importando vacinas...")
            import_vaccinations(cur, client_map, animal_map)
            print("[migrate] importando retornos de vacina...")
            import_vaccine_returns(cur, client_map, animal_map)
            print("[migrate] importando exames...")
            import_exams(cur, client_map, animal_map)
            print("[migrate] importando receituário...")
            import_prescriptions(cur, client_map, animal_map)
            print("[migrate] importando pesagens...")
            import_weights(cur, client_map, animal_map)
            print("[migrate] importando agendamentos...")
            import_appointments(cur, client_map, animal_map)
            print("[migrate] importando cirurgias...")
            import_surgeries(cur, client_map, animal_map)
            print("[migrate] importando anotações...")
            import_notes(cur, client_map, animal_map)

        if args.dry_run:
            conn.rollback()
            print("Dry-run concluÃ­do com rollback.")
        else:
            conn.commit()
            print("MigraÃ§Ã£o concluÃ­da com commit.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

