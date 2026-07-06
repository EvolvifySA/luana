-- Evolvify / Sistema Vet
-- Schema PostgreSQL normalizado para Supabase.
-- Baseado nos CSVs atuais e nas rotas manuais já existentes no app.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ---------------------------------------------------------------------
-- Usuários
-- ---------------------------------------------------------------------
create table if not exists public.users (
  id uuid primary key default gen_random_uuid(),
  username text not null unique,
  password_hash text not null,
  full_name text,
  email text,
  auth_user_id uuid,
  role text not null default 'staff' check (role in ('admin', 'staff', 'vet', 'owner')),
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

do $$
begin
  if not exists (select 1 from pg_trigger where tgname = 'trg_users_updated_at') then
    create trigger trg_users_updated_at
    before update on public.users
    for each row execute function public.set_updated_at();
  end if;
end
$$;

create index if not exists idx_users_username_lower on public.users (lower(username));
create unique index if not exists idx_users_email_lower on public.users (lower(email)) where email is not null;
create unique index if not exists idx_users_auth_user_id on public.users (auth_user_id) where auth_user_id is not null;

-- ---------------------------------------------------------------------
-- Clientes
-- ---------------------------------------------------------------------
create table if not exists public.clients (
  id uuid primary key default gen_random_uuid(),
  legacy_client_id text unique,
  name text not null,
  cpf text,
  mobile text,
  phone text,
  email text,
  address text,
  city text,
  neighborhood text,
  state text,
  zip_code text,
  birth_date date,
  notes text,
  source text not null default 'manual' check (source in ('manual', 'csv', 'import', 'system')),
  source_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

do $$
begin
  if not exists (select 1 from pg_trigger where tgname = 'trg_clients_updated_at') then
    create trigger trg_clients_updated_at
    before update on public.clients
    for each row execute function public.set_updated_at();
  end if;
end
$$;

create index if not exists idx_clients_name_lower on public.clients (lower(name));
create index if not exists idx_clients_legacy_client_id on public.clients (legacy_client_id);
create index if not exists idx_clients_cpf on public.clients (cpf);

alter table public.clients add column if not exists neighborhood text;
alter table public.clients add column if not exists state text;
alter table public.clients add column if not exists number text;

-- ---------------------------------------------------------------------
-- Animais
-- ---------------------------------------------------------------------
create table if not exists public.animals (
  id uuid primary key default gen_random_uuid(),
  legacy_animal_id text,
  client_id uuid not null references public.clients(id) on delete cascade,
  name text not null,
  species text,
  breed text,
  sex text,
  birth_date date,
  coat text,
  chip text,
  castrado boolean,
  card_number text,
  deceased_at date,
  notes text,
  source text not null default 'manual' check (source in ('manual', 'csv', 'import', 'system')),
  source_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (client_id, legacy_animal_id)
);

do $$
begin
  if not exists (select 1 from pg_trigger where tgname = 'trg_animals_updated_at') then
    create trigger trg_animals_updated_at
    before update on public.animals
    for each row execute function public.set_updated_at();
  end if;
end
$$;

create index if not exists idx_animals_client_id on public.animals (client_id);
create index if not exists idx_animals_legacy_animal_id on public.animals (legacy_animal_id);
create index if not exists idx_animals_name_lower on public.animals (lower(name));

alter table public.animals add column if not exists castrado boolean;

-- ---------------------------------------------------------------------
-- Serviços
-- ---------------------------------------------------------------------
create table if not exists public.services (
  id uuid primary key default gen_random_uuid(),
  legacy_name text,
  name text not null,
  price numeric(12,2) not null default 0,
  service_type text not null default 'clinica' check (service_type in ('clinica', 'petshop', 'produto', 'laboratorio', 'outro')),
  active boolean not null default true,
  notes text,
  source text not null default 'csv' check (source in ('manual', 'csv', 'import', 'system')),
  source_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (name, service_type)
);

do $$
begin
  if not exists (select 1 from pg_trigger where tgname = 'trg_services_updated_at') then
    create trigger trg_services_updated_at
    before update on public.services
    for each row execute function public.set_updated_at();
  end if;
end
$$;

create index if not exists idx_services_name_lower on public.services (lower(name));
create index if not exists idx_services_active on public.services (active);

-- ---------------------------------------------------------------------
-- Tickets
-- ---------------------------------------------------------------------
create table if not exists public.tickets (
  id uuid primary key default gen_random_uuid(),
  legacy_ticket_id text unique,
  legacy_financeiro_id text,
  client_id uuid not null references public.clients(id) on delete restrict,
  animal_id uuid references public.animals(id) on delete set null,
  ticket_date date not null,
  veterinarian text,
  status text not null default 'paid' check (status in ('paid', 'pending', 'cancelled', 'draft')),
  subtotal_services numeric(12,2) not null default 0,
  subtotal_products numeric(12,2) not null default 0,
  discount_total numeric(12,2) not null default 0,
  gross_total numeric(12,2) not null default 0,
  net_total numeric(12,2) not null default 0,
  payment_method text,
  notes text,
  source text not null default 'manual' check (source in ('manual', 'csv', 'import', 'system')),
  source_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

do $$
begin
  if not exists (select 1 from pg_trigger where tgname = 'trg_tickets_updated_at') then
    create trigger trg_tickets_updated_at
    before update on public.tickets
    for each row execute function public.set_updated_at();
  end if;
end
$$;

create index if not exists idx_tickets_client_id on public.tickets (client_id);
create index if not exists idx_tickets_animal_id on public.tickets (animal_id);
create index if not exists idx_tickets_ticket_date on public.tickets (ticket_date desc);
create index if not exists idx_tickets_status on public.tickets (status);
create index if not exists idx_tickets_legacy_ticket_id on public.tickets (legacy_ticket_id);

create table if not exists public.ticket_items (
  id uuid primary key default gen_random_uuid(),
  ticket_id uuid not null references public.tickets(id) on delete cascade,
  service_id uuid references public.services(id) on delete set null,
  description text not null,
  item_type text not null default 'clinica' check (item_type in ('clinica', 'petshop', 'produto', 'laboratorio', 'outro')),
  quantity integer not null default 1 check (quantity > 0),
  unit_price numeric(12,2) not null default 0,
  discount numeric(12,2) not null default 0,
  subtotal numeric(12,2) not null default 0,
  notes text,
  source text not null default 'manual' check (source in ('manual', 'csv', 'import', 'system')),
  source_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_ticket_items_ticket_id on public.ticket_items (ticket_id);
create index if not exists idx_ticket_items_service_id on public.ticket_items (service_id);

-- ---------------------------------------------------------------------
-- Receitas
-- ---------------------------------------------------------------------
create table if not exists public.prescriptions (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references public.clients(id) on delete restrict,
  animal_id uuid references public.animals(id) on delete set null,
  prescription_type text not null default 'simple' check (prescription_type in ('simple', 'controlled')),
  prescribed_at date not null,
  veterinarian text,
  crmv text,
  notes text,
  source text not null default 'manual' check (source in ('manual', 'csv', 'import', 'system')),
  source_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

do $$
begin
  if not exists (select 1 from pg_trigger where tgname = 'trg_prescriptions_updated_at') then
    create trigger trg_prescriptions_updated_at
    before update on public.prescriptions
    for each row execute function public.set_updated_at();
  end if;
end
$$;

create index if not exists idx_prescriptions_client_id on public.prescriptions (client_id);
create index if not exists idx_prescriptions_animal_id on public.prescriptions (animal_id);
create index if not exists idx_prescriptions_prescribed_at on public.prescriptions (prescribed_at desc);

create table if not exists public.prescription_items (
  id uuid primary key default gen_random_uuid(),
  prescription_id uuid not null references public.prescriptions(id) on delete cascade,
  category text not null check (category in ('oral', 'topical')),
  sequence integer not null default 1 check (sequence > 0),
  medication text not null,
  quantity text,
  instructions text,
  raw_text text,
  source text not null default 'manual' check (source in ('manual', 'csv', 'import', 'system')),
  source_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_prescription_items_prescription_id on public.prescription_items (prescription_id);
create index if not exists idx_prescription_items_category on public.prescription_items (category);

-- ---------------------------------------------------------------------
-- Agendamentos
-- ---------------------------------------------------------------------
create table if not exists public.appointments (
  id uuid primary key default gen_random_uuid(),
  client_id uuid references public.clients(id) on delete cascade,
  animal_id uuid references public.animals(id) on delete cascade,
  legacy_appointment_id text unique,
  appointment_date date not null,
  start_time time,
  end_time time,
  agenda_type text,
  taxi_dog boolean not null default false,
  employee_name text,
  notes text,
  status text not null default 'scheduled' check (status in ('scheduled', 'waiting', 'attended', 'absent', 'cancelled', 'done')),
  notified boolean not null default false,
  read_flag boolean not null default false,
  source text not null default 'csv' check (source in ('manual', 'csv', 'import', 'system')),
  source_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

do $$
begin
  if not exists (select 1 from pg_trigger where tgname = 'trg_appointments_updated_at') then
    create trigger trg_appointments_updated_at
    before update on public.appointments
    for each row execute function public.set_updated_at();
  end if;
end
$$;

create index if not exists idx_appointments_client_id on public.appointments (client_id);
create index if not exists idx_appointments_animal_id on public.appointments (animal_id);
create index if not exists idx_appointments_appointment_date on public.appointments (appointment_date desc);

-- ---------------------------------------------------------------------
-- Consultas
-- ---------------------------------------------------------------------
create table if not exists public.consultations (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references public.clients(id) on delete cascade,
  animal_id uuid references public.animals(id) on delete cascade,
  legacy_consultation_id text unique,
  consultation_date date,
  is_return boolean not null default false,
  return_date date,
  start_time time,
  end_time time,
  duration_minutes integer,
  veterinarian text,
  crmv text,
  status text not null default 'draft' check (status in ('draft', 'open', 'done', 'cancelled')),
  chief_complaint text,
  anamnesis text,
  digestive_system text,
  cardiorespiratory_system text,
  genitourinary_system text,
  nervous_musculoskeletal_system text,
  central_temperature text,
  peripheral_temperature text,
  heart_rate text,
  respiratory_rate text,
  tpc text,
  lymph_nodes text,
  mucosa text,
  hydration text,
  ectoparasites text,
  abdominal_palpation text,
  cardiac_auscultation text,
  pulmonary_auscultation text,
  blood_pressure text,
  glycemia text,
  delta text,
  weight text,
  clinical_suspicion text,
  requested_exams text,
  diagnosis text,
  outpatient_treatment text,
  integumentary_system text,
  previous_diseases_treatments text,
  observations text,
  notes text,
  source text not null default 'csv' check (source in ('manual', 'csv', 'import', 'system')),
  source_payload jsonb not null default '{}'::jsonb,
  completed_at timestamptz,
  completed_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

do $$
begin
  if not exists (select 1 from pg_trigger where tgname = 'trg_consultations_updated_at') then
    create trigger trg_consultations_updated_at
    before update on public.consultations
    for each row execute function public.set_updated_at();
  end if;
end
$$;

alter table public.consultations add column if not exists is_return boolean not null default false;
alter table public.consultations add column if not exists crmv text;
alter table public.consultations add column if not exists status text not null default 'draft';
alter table public.consultations add column if not exists chief_complaint text;
alter table public.consultations add column if not exists anamnesis text;
alter table public.consultations add column if not exists digestive_system text;
alter table public.consultations add column if not exists cardiorespiratory_system text;
alter table public.consultations add column if not exists genitourinary_system text;
alter table public.consultations add column if not exists nervous_musculoskeletal_system text;
alter table public.consultations add column if not exists central_temperature text;
alter table public.consultations add column if not exists peripheral_temperature text;
alter table public.consultations add column if not exists heart_rate text;
alter table public.consultations add column if not exists respiratory_rate text;
alter table public.consultations add column if not exists tpc text;
alter table public.consultations add column if not exists lymph_nodes text;
alter table public.consultations add column if not exists mucosa text;
alter table public.consultations add column if not exists hydration text;
alter table public.consultations add column if not exists ectoparasites text;
alter table public.consultations add column if not exists abdominal_palpation text;
alter table public.consultations add column if not exists cardiac_auscultation text;
alter table public.consultations add column if not exists pulmonary_auscultation text;
alter table public.consultations add column if not exists blood_pressure text;
alter table public.consultations add column if not exists glycemia text;
alter table public.consultations add column if not exists delta text;
alter table public.consultations add column if not exists weight text;
alter table public.consultations add column if not exists clinical_suspicion text;
alter table public.consultations add column if not exists requested_exams text;
alter table public.consultations add column if not exists diagnosis text;
alter table public.consultations add column if not exists outpatient_treatment text;
alter table public.consultations add column if not exists integumentary_system text;
alter table public.consultations add column if not exists previous_diseases_treatments text;
alter table public.consultations add column if not exists observations text;
alter table public.consultations add column if not exists completed_at timestamptz;
alter table public.consultations add column if not exists completed_by text;
alter table public.consultations add column if not exists notes text;
alter table public.consultations add column if not exists consultation_date date;
alter table public.consultations add column if not exists return_date date;
alter table public.consultations add column if not exists start_time time;
alter table public.consultations add column if not exists end_time time;
alter table public.consultations add column if not exists duration_minutes integer;
alter table public.consultations add column if not exists veterinarian text;

create index if not exists idx_consultations_client_id on public.consultations (client_id);
create index if not exists idx_consultations_animal_id on public.consultations (animal_id);
create index if not exists idx_consultations_date on public.consultations (consultation_date desc);
create index if not exists idx_consultations_status on public.consultations (status);
create index if not exists idx_consultations_return_date on public.consultations (return_date desc);

-- ---------------------------------------------------------------------
-- Vacinas
-- ---------------------------------------------------------------------
create table if not exists public.vaccinations (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references public.clients(id) on delete cascade,
  animal_id uuid references public.animals(id) on delete cascade,
  legacy_vaccination_id text unique,
  vaccine_name text not null,
  dose text,
  applied_at date not null,
  return_at date,
  notes text,
  veterinarian text,
  return_attended boolean,
  return_notified boolean,
  return_read boolean,
  source text not null default 'csv' check (source in ('manual', 'csv', 'import', 'system')),
  source_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

do $$
begin
  if not exists (select 1 from pg_trigger where tgname = 'trg_vaccinations_updated_at') then
    create trigger trg_vaccinations_updated_at
    before update on public.vaccinations
    for each row execute function public.set_updated_at();
  end if;
end
$$;

create index if not exists idx_vaccinations_client_id on public.vaccinations (client_id);
create index if not exists idx_vaccinations_animal_id on public.vaccinations (animal_id);
create index if not exists idx_vaccinations_applied_at on public.vaccinations (applied_at desc);

-- ---------------------------------------------------------------------
-- Retornos de vacina
-- ---------------------------------------------------------------------
create table if not exists public.vaccine_returns (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references public.clients(id) on delete cascade,
  animal_id uuid references public.animals(id) on delete cascade,
  legacy_return_id text unique,
  return_date date not null,
  vaccine_name text,
  vaccine_date date,
  applied_by text,
  notify_sent boolean,
  return_attended boolean,
  return_read boolean,
  notes text,
  source text not null default 'csv' check (source in ('manual', 'csv', 'import', 'system')),
  source_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

do $$
begin
  if not exists (select 1 from pg_trigger where tgname = 'trg_vaccine_returns_updated_at') then
    create trigger trg_vaccine_returns_updated_at
    before update on public.vaccine_returns
    for each row execute function public.set_updated_at();
  end if;
end
$$;

create index if not exists idx_vaccine_returns_client_id on public.vaccine_returns (client_id);
create index if not exists idx_vaccine_returns_animal_id on public.vaccine_returns (animal_id);
create index if not exists idx_vaccine_returns_return_date on public.vaccine_returns (return_date desc);

-- ---------------------------------------------------------------------
-- Exames
-- ---------------------------------------------------------------------
create table if not exists public.exams (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references public.clients(id) on delete cascade,
  animal_id uuid references public.animals(id) on delete cascade,
  legacy_exam_id text unique,
  exam_date date,
  registered_at date,
  exam_type text,
  status text,
  file_path text,
  source_url text,
  requires_browser boolean not null default false,
  reviewed boolean,
  requester text,
  external_requester text,
  sent_by text,
  notes text,
  source text not null default 'csv' check (source in ('manual', 'csv', 'import', 'system')),
  source_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

do $$
begin
  if not exists (select 1 from pg_trigger where tgname = 'trg_exams_updated_at') then
    create trigger trg_exams_updated_at
    before update on public.exams
    for each row execute function public.set_updated_at();
  end if;
end
$$;

create index if not exists idx_exams_client_id on public.exams (client_id);
create index if not exists idx_exams_animal_id on public.exams (animal_id);
create index if not exists idx_exams_exam_date on public.exams (exam_date desc);
create index if not exists idx_exams_legacy_exam_id on public.exams (legacy_exam_id);

-- ---------------------------------------------------------------------
-- Pesagens
-- ---------------------------------------------------------------------
create table if not exists public.weights (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references public.clients(id) on delete cascade,
  animal_id uuid references public.animals(id) on delete cascade,
  legacy_weight_id text unique,
  weighed_at date not null,
  weight numeric(8,2) not null,
  recorded_by text,
  notes text,
  source text not null default 'csv' check (source in ('manual', 'csv', 'import', 'system')),
  source_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

do $$
begin
  if not exists (select 1 from pg_trigger where tgname = 'trg_weights_updated_at') then
    create trigger trg_weights_updated_at
    before update on public.weights
    for each row execute function public.set_updated_at();
  end if;
end
$$;

create index if not exists idx_weights_client_id on public.weights (client_id);
create index if not exists idx_weights_animal_id on public.weights (animal_id);
create index if not exists idx_weights_weighed_at on public.weights (weighed_at desc);

-- ---------------------------------------------------------------------
-- Cirurgias
-- ---------------------------------------------------------------------
create table if not exists public.surgeries (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references public.clients(id) on delete cascade,
  animal_id uuid references public.animals(id) on delete cascade,
  legacy_surgery_id text unique,
  surgery_date date,
  title text,
  veterinarian text,
  notes text,
  source text not null default 'csv' check (source in ('manual', 'csv', 'import', 'system')),
  source_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

do $$
begin
  if not exists (select 1 from pg_trigger where tgname = 'trg_surgeries_updated_at') then
    create trigger trg_surgeries_updated_at
    before update on public.surgeries
    for each row execute function public.set_updated_at();
  end if;
end
$$;

create index if not exists idx_surgeries_client_id on public.surgeries (client_id);
create index if not exists idx_surgeries_animal_id on public.surgeries (animal_id);
create index if not exists idx_surgeries_surgery_date on public.surgeries (surgery_date desc);

-- ---------------------------------------------------------------------
-- Anotações
-- ---------------------------------------------------------------------
create table if not exists public.notes (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references public.clients(id) on delete cascade,
  animal_id uuid references public.animals(id) on delete cascade,
  legacy_note_id text unique,
  note_date date,
  title text,
  veterinarian text,
  body text,
  source text not null default 'csv' check (source in ('manual', 'csv', 'import', 'system')),
  source_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

do $$
begin
  if not exists (select 1 from pg_trigger where tgname = 'trg_notes_updated_at') then
    create trigger trg_notes_updated_at
    before update on public.notes
    for each row execute function public.set_updated_at();
  end if;
end
$$;

create index if not exists idx_notes_client_id on public.notes (client_id);
create index if not exists idx_notes_animal_id on public.notes (animal_id);
create index if not exists idx_notes_note_date on public.notes (note_date desc);

-- ---------------------------------------------------------------------
-- Documentos
-- ---------------------------------------------------------------------
create table if not exists public.documents (
  id uuid primary key default gen_random_uuid(),
  client_id uuid references public.clients(id) on delete set null,
  animal_id uuid references public.animals(id) on delete set null,
  exam_id uuid references public.exams(id) on delete cascade,
  ticket_id uuid references public.tickets(id) on delete cascade,
  prescription_id uuid references public.prescriptions(id) on delete cascade,
  consultation_id uuid references public.consultations(id) on delete cascade,
  note_id uuid references public.notes(id) on delete cascade,
  file_name text not null,
  mime_type text,
  storage_path text not null,
  source_url text,
  caption text,
  metadata jsonb not null default '{}'::jsonb,
  source text not null default 'manual' check (source in ('manual', 'csv', 'import', 'system')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (
    client_id is not null
    or animal_id is not null
    or exam_id is not null
    or ticket_id is not null
    or prescription_id is not null
    or consultation_id is not null
    or note_id is not null
  )
);

do $$
begin
  if not exists (select 1 from pg_trigger where tgname = 'trg_documents_updated_at') then
    create trigger trg_documents_updated_at
    before update on public.documents
    for each row execute function public.set_updated_at();
  end if;
end
$$;

create index if not exists idx_documents_client_id on public.documents (client_id);
create index if not exists idx_documents_animal_id on public.documents (animal_id);
create index if not exists idx_documents_exam_id on public.documents (exam_id);
create index if not exists idx_documents_ticket_id on public.documents (ticket_id);
create index if not exists idx_documents_prescription_id on public.documents (prescription_id);
create index if not exists idx_documents_storage_path on public.documents (storage_path);

-- ---------------------------------------------------------------------
-- Importação / rastreabilidade
-- ---------------------------------------------------------------------
create table if not exists public.import_batches (
  id uuid primary key default gen_random_uuid(),
  source_file text not null,
  entity_name text not null,
  checksum text,
  row_count integer not null default 0 check (row_count >= 0),
  imported_at timestamptz not null default now(),
  imported_by text,
  notes text
);

create index if not exists idx_import_batches_entity_name on public.import_batches (entity_name);
create index if not exists idx_import_batches_source_file on public.import_batches (source_file);

create table if not exists public.import_rows (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid not null references public.import_batches(id) on delete cascade,
  entity_name text not null,
  legacy_key text,
  row_number integer,
  raw_data jsonb not null default '{}'::jsonb,
  normalized_data jsonb not null default '{}'::jsonb,
  status text not null default 'ok' check (status in ('ok', 'skipped', 'error')),
  error_message text,
  created_at timestamptz not null default now()
);

create index if not exists idx_import_rows_batch_id on public.import_rows (batch_id);
create index if not exists idx_import_rows_entity_name on public.import_rows (entity_name);
create index if not exists idx_import_rows_legacy_key on public.import_rows (legacy_key);

-- ---------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------
alter table public.users enable row level security;
alter table public.clients enable row level security;
alter table public.animals enable row level security;
alter table public.services enable row level security;
alter table public.tickets enable row level security;
alter table public.ticket_items enable row level security;
alter table public.prescriptions enable row level security;
alter table public.prescription_items enable row level security;
alter table public.appointments enable row level security;
alter table public.consultations enable row level security;
alter table public.vaccinations enable row level security;
alter table public.vaccine_returns enable row level security;
alter table public.exams enable row level security;
alter table public.weights enable row level security;
alter table public.surgeries enable row level security;
alter table public.notes enable row level security;
alter table public.documents enable row level security;
alter table public.import_batches enable row level security;
alter table public.import_rows enable row level security;

-- Backend via service role pode operar sem policies. Se quiser acesso
-- direto pelo browser no futuro, criar policies específicas depois.
