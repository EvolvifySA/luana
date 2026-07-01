-- Evolvify / Sistema Vet
-- Índices de desempenho para o banco no Supabase.
--
-- Rode este script uma vez no SQL Editor do Supabase (ou via psql).
-- É idempotente (IF NOT EXISTS) e seguro de reaplicar.
--
-- Contexto: as tabelas são pequenas hoje, mas as chaves estrangeiras e as
-- colunas usadas em filtros/ordenções não tinham índice. Isso evita seq scans
-- conforme a base cresce e acelera as páginas de cliente, financeiro e dashboard.

-- ─── Chaves estrangeiras (joins e filtros por dono) ─────────────────────────
create extension if not exists pg_trgm;

create index if not exists idx_animals_client_id            on public.animals(client_id);

create index if not exists idx_tickets_client_id            on public.tickets(client_id);
create index if not exists idx_tickets_animal_id            on public.tickets(animal_id);
create index if not exists idx_ticket_items_ticket_id       on public.ticket_items(ticket_id);
create index if not exists idx_ticket_items_service_id      on public.ticket_items(service_id);

create index if not exists idx_consultations_client_id      on public.consultations(client_id);
create index if not exists idx_consultations_animal_id      on public.consultations(animal_id);

create index if not exists idx_prescriptions_client_id      on public.prescriptions(client_id);
create index if not exists idx_prescriptions_animal_id      on public.prescriptions(animal_id);
create index if not exists idx_prescription_items_presc_id  on public.prescription_items(prescription_id);

create index if not exists idx_vaccinations_client_id       on public.vaccinations(client_id);
create index if not exists idx_vaccinations_animal_id       on public.vaccinations(animal_id);

create index if not exists idx_vaccine_returns_client_id    on public.vaccine_returns(client_id);
create index if not exists idx_vaccine_returns_animal_id    on public.vaccine_returns(animal_id);

create index if not exists idx_exams_client_id              on public.exams(client_id);
create index if not exists idx_exams_animal_id              on public.exams(animal_id);

create index if not exists idx_weights_client_id            on public.weights(client_id);
create index if not exists idx_weights_animal_id            on public.weights(animal_id);

create index if not exists idx_surgeries_client_id          on public.surgeries(client_id);
create index if not exists idx_surgeries_animal_id          on public.surgeries(animal_id);

create index if not exists idx_notes_client_id              on public.notes(client_id);
create index if not exists idx_notes_animal_id              on public.notes(animal_id);

create index if not exists idx_appointments_client_id       on public.appointments(client_id);
create index if not exists idx_appointments_animal_id       on public.appointments(animal_id);

create index if not exists idx_documents_client_id          on public.documents(client_id);
create index if not exists idx_documents_animal_id          on public.documents(animal_id);

-- ─── Filtros/ordenções por data e status (dashboard e financeiro) ───────────
create index if not exists idx_tickets_ticket_date          on public.tickets(ticket_date);
create index if not exists idx_tickets_status               on public.tickets(status);
create index if not exists idx_consultations_consult_date   on public.consultations(consultation_date);
create index if not exists idx_vaccinations_applied_at      on public.vaccinations(applied_at);
create index if not exists idx_appointments_date            on public.appointments(appointment_date);

-- ─── Busca/ordenção de clientes por nome (lista /clientes) ──────────────────
-- A listagem usa `order by lower(name)`; o índice abaixo cobre essa ordenação.
create index if not exists idx_clients_lower_name           on public.clients(lower(name));
create index if not exists idx_clients_lower_name_trgm      on public.clients using gin (lower(name) gin_trgm_ops);

-- Resolução de registros legados (importação CSV) por chave legada.
create index if not exists idx_animals_legacy_animal_id     on public.animals(legacy_animal_id);

-- Atualiza estatísticas para o planejador usar os novos índices.
analyze;
