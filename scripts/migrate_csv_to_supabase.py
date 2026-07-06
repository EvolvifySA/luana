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
MIGRATION_MAX_ROWS = 0
MIGRATION_RECORD_TRACE = True


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


def _maybe_limit(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    if MIGRATION_MAX_ROWS and len(rows) > MIGRATION_MAX_ROWS:
        return rows[:MIGRATION_MAX_ROWS]
    return rows


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
    if not MIGRATION_RECORD_TRACE:
        return
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
        "address": (row.get("endereço") or row.get("endereco") or row.get("endereÃ§o") or row.get("Nome") or "").strip() or None,
        "city": (row.get("cidade") or "").strip() or None,
        "zip_code": (row.get("cep") or "").strip() or None,
        "birth_date": _parse_date(row.get("nascimento") or ""),
        "notes": (row.get("observação") or row.get("observacao") or row.get("observaÃ§Ã£o") or "").strip() or None,
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
    rows = _maybe_limit(_read_csv(DATA_DIR / "clientes.csv"))
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
    rows = _maybe_limit(_read_csv(DATA_DIR / "animais.csv"))
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
    rows = _maybe_limit(_read_csv(DATA_DIR / "servicos.csv"))
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
    rows = _maybe_limit(_read_csv(DATA_DIR / "tickets.csv"))
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


def _bool_from_text(value: str | None) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"sim", "s", "yes", "y", "true", "1", "x"}:
        return True
    if text in {"nao", "não", "n", "no", "false", "0"}:
        return False
    return None


def _time_from_text(value: str | None):
    if not value:
        return None
    value = str(value).strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    return None


def _derived_legacy_id(*parts) -> str:
    return "|".join("" if p is None else str(p).strip() for p in parts)


def import_consultations(cur, client_map: dict[str, str], animal_map: dict[tuple[str, str], str]):
    rows = _maybe_limit(_read_csv(DATA_DIR / "consultas.csv"))
    if not rows:
        return
    batch_id = _batch(cur, "consultas.csv", "consultations", len(rows))
    print(f"[migrate] consultations: {len(rows)} linhas")
    for i, row in enumerate(rows, 1):
        client_id, animal_id = _resolve_ids(
            cur,
            client_map,
            animal_map,
            row.get("id_cliente", "").strip(),
            row.get("id_animal", "").strip(),
        )
        if not client_id:
            continue
        normalized = {
            "client_id": client_id,
            "animal_id": animal_id,
            "legacy_consultation_id": _derived_legacy_id(
                row.get("id_cliente", ""),
                row.get("id_animal", ""),
                row.get("Data da consulta", ""),
                row.get("Início", ""),
                row.get("Término", ""),
                i,
            ),
            "consultation_date": _parse_date(row.get("Data da consulta")) or _parse_date(row.get("Data")),
            "return_date": _parse_date(row.get("Data do retorno")),
            "start_time": _time_from_text(row.get("Início")),
            "end_time": _time_from_text(row.get("Término")),
            "duration_minutes": None,
            "veterinarian": (row.get("Veterinário") or "").strip() or None,
            "notes": (row.get("Observação") or "").strip() or None,
            "source": "csv",
            "source_payload": row,
        }
        if row.get("Duração da consulta"):
            duration = row.get("Duração da consulta").strip()
            try:
                hh, mm, ss = duration.split(":")
                normalized["duration_minutes"] = int(hh) * 60 + int(mm) + (1 if int(ss) >= 30 else 0)
            except Exception:
                normalized["duration_minutes"] = None
        db_values = dict(normalized)
        db_values["source_payload"] = Json(row, dumps=_json_dumps)
        cur.execute(
            """
            insert into public.consultations
              (client_id, animal_id, legacy_consultation_id, consultation_date, return_date, start_time, end_time, duration_minutes, veterinarian, notes, source, source_payload)
            values
              (%(client_id)s, %(animal_id)s, %(legacy_consultation_id)s, %(consultation_date)s, %(return_date)s, %(start_time)s, %(end_time)s, %(duration_minutes)s, %(veterinarian)s, %(notes)s, %(source)s, %(source_payload)s)
            on conflict (legacy_consultation_id)
            do update set
              client_id = excluded.client_id,
              animal_id = excluded.animal_id,
              consultation_date = excluded.consultation_date,
              return_date = excluded.return_date,
              start_time = excluded.start_time,
              end_time = excluded.end_time,
              duration_minutes = excluded.duration_minutes,
              veterinarian = excluded.veterinarian,
              notes = excluded.notes,
              source = excluded.source,
              source_payload = excluded.source_payload
            """,
            db_values,
        )
        _insert_import_row(cur, batch_id, "consultations", normalized["legacy_consultation_id"], i, row, normalized)
        if i % 100 == 0 or i == len(rows):
            print(f"[migrate] consultations: {i}/{len(rows)}")


def import_vaccinations(cur, client_map: dict[str, str], animal_map: dict[tuple[str, str], str]):
    rows = _maybe_limit(_read_csv(DATA_DIR / "vacinas.csv"))
    if not rows:
        return
    batch_id = _batch(cur, "vacinas.csv", "vaccinations", len(rows))
    print(f"[migrate] vaccinations: {len(rows)} linhas")
    for i, row in enumerate(rows, 1):
        client_id, animal_id = _resolve_ids(cur, client_map, animal_map, row.get("id_cliente", "").strip(), row.get("id_animal", "").strip())
        if not client_id:
            continue
        normalized = {
            "client_id": client_id,
            "animal_id": animal_id,
            "legacy_vaccination_id": _derived_legacy_id(row.get("id_cliente", ""), row.get("id_animal", ""), row.get("Vacina aplicada", ""), row.get("Data da aplicação", ""), i),
            "vaccine_name": (row.get("Vacina aplicada") or "").strip(),
            "dose": (row.get("Dose") or "").strip() or None,
            "applied_at": _parse_date(row.get("Data da aplicação")) or date.today(),
            "return_at": _parse_date(row.get("Retorno")),
            "notes": (row.get("Observação") or "").strip() or None,
            "veterinarian": (row.get("Aplicado por") or "").strip() or None,
            "return_attended": _bool_from_text(row.get("Compareceu retorno?")),
            "return_notified": _bool_from_text(row.get("Avisado retorno?")),
            "return_read": _bool_from_text(row.get("Lido retorno?")),
            "source": "csv",
            "source_payload": row,
        }
        db_values = dict(normalized)
        db_values["source_payload"] = Json(row, dumps=_json_dumps)
        cur.execute(
            """
            insert into public.vaccinations
              (client_id, animal_id, legacy_vaccination_id, vaccine_name, dose, applied_at, return_at, notes, veterinarian, return_attended, return_notified, return_read, source, source_payload)
            values
              (%(client_id)s, %(animal_id)s, %(legacy_vaccination_id)s, %(vaccine_name)s, %(dose)s, %(applied_at)s, %(return_at)s, %(notes)s, %(veterinarian)s, %(return_attended)s, %(return_notified)s, %(return_read)s, %(source)s, %(source_payload)s)
            on conflict (legacy_vaccination_id)
            do update set
              client_id = excluded.client_id,
              animal_id = excluded.animal_id,
              vaccine_name = excluded.vaccine_name,
              dose = excluded.dose,
              applied_at = excluded.applied_at,
              return_at = excluded.return_at,
              notes = excluded.notes,
              veterinarian = excluded.veterinarian,
              return_attended = excluded.return_attended,
              return_notified = excluded.return_notified,
              return_read = excluded.return_read,
              source = excluded.source,
              source_payload = excluded.source_payload
            """,
            db_values,
        )
        _insert_import_row(cur, batch_id, "vaccinations", normalized["legacy_vaccination_id"], i, row, normalized)
        if i % 100 == 0 or i == len(rows):
            print(f"[migrate] vaccinations: {i}/{len(rows)}")


def import_vaccine_returns(cur, client_map: dict[str, str], animal_map: dict[tuple[str, str], str]):
    rows = _maybe_limit(_read_csv(DATA_DIR / "retorno_vacinas.csv"))
    if not rows:
        return
    batch_id = _batch(cur, "retorno_vacinas.csv", "vaccine_returns", len(rows))
    print(f"[migrate] vaccine_returns: {len(rows)} linhas")
    for i, row in enumerate(rows, 1):
        client_id, animal_id = _resolve_ids(cur, client_map, animal_map, row.get("id_cliente", "").strip(), row.get("id_animal", "").strip())
        if not client_id:
            continue
        normalized = {
            "client_id": client_id,
            "animal_id": animal_id,
            "legacy_return_id": _derived_legacy_id(row.get("Cliente", ""), row.get("Animal", ""), row.get("Vacina", ""), row.get("Data do retorno", ""), i),
            "return_date": _parse_date(row.get("Data do retorno")) or date.today(),
            "vaccine_name": (row.get("Vacina") or "").strip() or None,
            "vaccine_date": _parse_date(row.get("Data da vacina")),
            "applied_by": (row.get("Aplicado por") or "").strip() or None,
            "notify_sent": _bool_from_text(row.get("Enviar aviso")),
            "return_attended": _bool_from_text(row.get("Compareceu retorno?")),
            "return_read": _bool_from_text(row.get("Lido retorno?")),
            "notes": (row.get("Observação") or "").strip() or None,
            "source": "csv",
            "source_payload": row,
        }
        db_values = dict(normalized)
        db_values["source_payload"] = Json(row, dumps=_json_dumps)
        cur.execute(
            """
            insert into public.vaccine_returns
              (client_id, animal_id, legacy_return_id, return_date, vaccine_name, vaccine_date, applied_by, notify_sent, return_attended, return_read, notes, source, source_payload)
            values
              (%(client_id)s, %(animal_id)s, %(legacy_return_id)s, %(return_date)s, %(vaccine_name)s, %(vaccine_date)s, %(applied_by)s, %(notify_sent)s, %(return_attended)s, %(return_read)s, %(notes)s, %(source)s, %(source_payload)s)
            on conflict (legacy_return_id)
            do update set
              client_id = excluded.client_id,
              animal_id = excluded.animal_id,
              return_date = excluded.return_date,
              vaccine_name = excluded.vaccine_name,
              vaccine_date = excluded.vaccine_date,
              applied_by = excluded.applied_by,
              notify_sent = excluded.notify_sent,
              return_attended = excluded.return_attended,
              return_read = excluded.return_read,
              notes = excluded.notes,
              source = excluded.source,
              source_payload = excluded.source_payload
            """,
            db_values,
        )
        _insert_import_row(cur, batch_id, "vaccine_returns", normalized["legacy_return_id"], i, row, normalized)
        if i % 100 == 0 or i == len(rows):
            print(f"[migrate] vaccine_returns: {i}/{len(rows)}")


def import_exams(cur, client_map: dict[str, str], animal_map: dict[tuple[str, str], str]):
    rows = _maybe_limit(_read_csv(DATA_DIR / "exames.csv"))
    if not rows:
        return
    batch_id = _batch(cur, "exames.csv", "exams", len(rows))
    print(f"[migrate] exams: {len(rows)} linhas")
    for i, row in enumerate(rows, 1):
        client_id, animal_id = _resolve_ids(cur, client_map, animal_map, row.get("id_cliente", "").strip(), row.get("id_animal", "").strip())
        if not client_id:
            continue
        file_path = (row.get("caminho_pdf") or "").strip() or None
        normalized = {
            "client_id": client_id,
            "animal_id": animal_id,
            "legacy_exam_id": _derived_legacy_id(row.get("id_cliente", ""), row.get("id_animal", ""), row.get("Tipo de exame", ""), row.get("Data do Exame", ""), i),
            "exam_date": _parse_date(row.get("Data do Exame")),
            "registered_at": _parse_date(row.get("Data do registro")),
            "exam_type": (row.get("Tipo de exame") or row.get("Tamanho") or "").strip() or None,
            "status": (row.get("Tipo") or "").strip() or None,
            "file_path": file_path,
            "source_url": (row.get("url_pdf") or "").strip() or None,
            "requires_browser": (row.get("Tipo") or "").strip().lower() == "requer_navegador",
            "reviewed": _bool_from_text(row.get("Laudado")),
            "requester": (row.get("Solicitante") or "").strip() or None,
            "external_requester": (row.get("Solicitante externo") or "").strip() or None,
            "sent_by": (row.get("Enviado por") or "").strip() or None,
            "notes": (row.get("Observação") or "").strip() or None,
            "source": "csv",
            "source_payload": row,
        }
        db_values = dict(normalized)
        db_values["source_payload"] = Json(row, dumps=_json_dumps)
        cur.execute(
            """
            insert into public.exams
              (client_id, animal_id, legacy_exam_id, exam_date, registered_at, exam_type, status, file_path, source_url, requires_browser, reviewed, requester, external_requester, sent_by, notes, source, source_payload)
            values
              (%(client_id)s, %(animal_id)s, %(legacy_exam_id)s, %(exam_date)s, %(registered_at)s, %(exam_type)s, %(status)s, %(file_path)s, %(source_url)s, %(requires_browser)s, %(reviewed)s, %(requester)s, %(external_requester)s, %(sent_by)s, %(notes)s, %(source)s, %(source_payload)s)
            on conflict (legacy_exam_id)
            do update set
              client_id = excluded.client_id,
              animal_id = excluded.animal_id,
              exam_date = excluded.exam_date,
              registered_at = excluded.registered_at,
              exam_type = excluded.exam_type,
              status = excluded.status,
              file_path = excluded.file_path,
              source_url = excluded.source_url,
              requires_browser = excluded.requires_browser,
              reviewed = excluded.reviewed,
              requester = excluded.requester,
              external_requester = excluded.external_requester,
              sent_by = excluded.sent_by,
              notes = excluded.notes,
              source = excluded.source,
              source_payload = excluded.source_payload
            """,
            db_values,
        )
        _insert_import_row(cur, batch_id, "exams", normalized["legacy_exam_id"], i, row, normalized)
        if i % 100 == 0 or i == len(rows):
            print(f"[migrate] exams: {i}/{len(rows)}")


def import_weights(cur, client_map: dict[str, str], animal_map: dict[tuple[str, str], str]):
    rows = _maybe_limit(_read_csv(DATA_DIR / "pesagens.csv"))
    if not rows:
        return
    batch_id = _batch(cur, "pesagens.csv", "weights", len(rows))
    print(f"[migrate] weights: {len(rows)} linhas")
    for i, row in enumerate(rows, 1):
        client_id, animal_id = _resolve_ids(cur, client_map, animal_map, row.get("id_cliente", "").strip(), row.get("id_animal", "").strip())
        if not client_id:
            continue
        normalized = {
            "client_id": client_id,
            "animal_id": animal_id,
            "legacy_weight_id": _derived_legacy_id(row.get("id_cliente", ""), row.get("id_animal", ""), row.get("Data da pesagem", ""), i),
            "weighed_at": _parse_date(row.get("Data da pesagem")) or date.today(),
            "weight": _parse_number(row.get("Peso")),
            "recorded_by": (row.get("Registrado por") or "").strip() or None,
            "notes": (row.get("Observação") or "").strip() or None,
            "source": "csv",
            "source_payload": row,
        }
        db_values = dict(normalized)
        db_values["source_payload"] = Json(row, dumps=_json_dumps)
        cur.execute(
            """
            insert into public.weights
              (client_id, animal_id, legacy_weight_id, weighed_at, weight, recorded_by, notes, source, source_payload)
            values
              (%(client_id)s, %(animal_id)s, %(legacy_weight_id)s, %(weighed_at)s, %(weight)s, %(recorded_by)s, %(notes)s, %(source)s, %(source_payload)s)
            on conflict (legacy_weight_id)
            do update set
              client_id = excluded.client_id,
              animal_id = excluded.animal_id,
              weighed_at = excluded.weighed_at,
              weight = excluded.weight,
              recorded_by = excluded.recorded_by,
              notes = excluded.notes,
              source = excluded.source,
              source_payload = excluded.source_payload
            """,
            db_values,
        )
        _insert_import_row(cur, batch_id, "weights", normalized["legacy_weight_id"], i, row, normalized)
        if i % 100 == 0 or i == len(rows):
            print(f"[migrate] weights: {i}/{len(rows)}")


def import_appointments(cur, client_map: dict[str, str], animal_map: dict[tuple[str, str], str]):
    rows = _maybe_limit(_read_csv(DATA_DIR / "agendamentos.csv"))
    if not rows:
        return
    batch_id = _batch(cur, "agendamentos.csv", "appointments", len(rows))
    print(f"[migrate] appointments: {len(rows)} linhas")
    for i, row in enumerate(rows, 1):
        client_id, animal_id = _resolve_ids(cur, client_map, animal_map, row.get("id_cliente", "").strip(), row.get("id_animal", "").strip())
        if not client_id:
            continue
        status_text = (row.get("Status") or "").strip().lower()
        normalized = {
            "client_id": client_id,
            "animal_id": animal_id,
            "legacy_appointment_id": _derived_legacy_id(row.get("id_cliente", ""), row.get("id_animal", ""), row.get("Data", ""), row.get("Inicio", ""), row.get("Final", ""), i),
            "appointment_date": _parse_date(row.get("Data")) or date.today(),
            "start_time": _time_from_text(row.get("Inicio")),
            "end_time": _time_from_text(row.get("Final")),
            "agenda_type": (row.get("Agenda") or "").strip() or None,
            "taxi_dog": _bool_from_text(row.get("Taxi dog")) or False,
            "employee_name": (row.get("Funcionário") or "").strip() or None,
            "notes": (row.get("Obs") or "").strip() or None,
            "status": "scheduled" if "aguard" in status_text else "attended" if "compareceu" in status_text else "absent" if "não compareceu" in status_text or "nao compareceu" in status_text else "scheduled",
            "notified": _bool_from_text(row.get("Avisado Whats")) if _bool_from_text(row.get("Avisado Whats")) is not None else False,
            "read_flag": _bool_from_text(row.get("Lido")) if _bool_from_text(row.get("Lido")) is not None else False,
            "source": "csv",
            "source_payload": row,
        }
        db_values = dict(normalized)
        db_values["source_payload"] = Json(row, dumps=_json_dumps)
        cur.execute(
            """
            insert into public.appointments
              (client_id, animal_id, legacy_appointment_id, appointment_date, start_time, end_time, agenda_type, taxi_dog, employee_name, notes, status, notified, read_flag, source, source_payload)
            values
              (%(client_id)s, %(animal_id)s, %(legacy_appointment_id)s, %(appointment_date)s, %(start_time)s, %(end_time)s, %(agenda_type)s, %(taxi_dog)s, %(employee_name)s, %(notes)s, %(status)s, %(notified)s, %(read_flag)s, %(source)s, %(source_payload)s)
            on conflict (legacy_appointment_id)
            do update set
              client_id = excluded.client_id,
              animal_id = excluded.animal_id,
              appointment_date = excluded.appointment_date,
              start_time = excluded.start_time,
              end_time = excluded.end_time,
              agenda_type = excluded.agenda_type,
              taxi_dog = excluded.taxi_dog,
              employee_name = excluded.employee_name,
              notes = excluded.notes,
              status = excluded.status,
              notified = excluded.notified,
              read_flag = excluded.read_flag,
              source = excluded.source,
              source_payload = excluded.source_payload
            """,
            db_values,
        )
        _insert_import_row(cur, batch_id, "appointments", normalized["legacy_appointment_id"], i, row, normalized)
        if i % 100 == 0 or i == len(rows):
            print(f"[migrate] appointments: {i}/{len(rows)}")


def import_prescriptions(cur, client_map: dict[str, str], animal_map: dict[tuple[str, str], str]):
    print("[migrate] prescriptions: sem CSV direto neste export, pulando")


def import_surgeries(cur, client_map: dict[str, str], animal_map: dict[tuple[str, str], str]):
    print("[migrate] surgeries: sem CSV direto neste export, pulando")


def import_notes(cur, client_map: dict[str, str], animal_map: dict[tuple[str, str], str]):
    print("[migrate] notes: sem CSV direto neste export, pulando")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Executa tudo em uma transaÃ§Ã£o e faz rollback.")
    parser.add_argument("--max-rows", type=int, default=0, help="Limita a importação por arquivo para uma amostra. 0 = sem limite.")
    parser.add_argument("--no-trace", action="store_true", help="Não grava import_rows/import_batches. Útil para dry-run rápido.")
    args = parser.parse_args()

    global MIGRATION_MAX_ROWS, MIGRATION_RECORD_TRACE
    MIGRATION_MAX_ROWS = max(0, int(args.max_rows or 0))
    MIGRATION_RECORD_TRACE = not args.no_trace and not args.dry_run

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

