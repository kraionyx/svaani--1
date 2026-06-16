-- ============================================================================
-- Svaani / Kraionyx — Supabase (Postgres) schema
-- ============================================================================
-- Run this in the Supabase SQL Editor (or `psql`) against a FRESH project.
--
-- DESIGN PRINCIPLES (match the existing app contract):
--   1. PHI NEVER stored as plaintext. Clinical content (transcript, clean,
--      extraction, note, risk, rendered prescription with patient data) is held
--      in *_enc columns as app-encrypted blobs (AES-256-GCM via the existing
--      app.security.crypto.FieldCipher). Supabase at-rest storage only ever sees
--      ciphertext. This mirrors app/store_sql.py.
--   2. Non-PHI METADATA (complexity, inference mode, confidence, speaker count,
--      model/prompt versions, error categories, statuses, timings) is stored as
--      plain, queryable columns so the admin console / analytics work.
--   3. Multi-tenant by hospital_id, enforced with Row Level Security (RLS).
--      The service_role key bypasses RLS (server-side only). The anon/authenticated
--      keys are constrained to their own hospital.
--   4. Append-only audit with a SHA-256 hash chain (mirrors security/audit.py;
--      the explainer's "blockchain audit"). UPDATE/DELETE revoked.
--
-- NOTE ON RESIDENCY: this project is in ap-southeast-1 (Singapore). The product's
-- PHI residency posture is India (asia-south1) per docs/ARCHITECTURE.md §7. Because
-- clinical PHI is stored encrypted (keys held outside Supabase), at-rest exposure is
-- mitigated, but confirm this is acceptable for DPDPA/ABDM before storing real PHI.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 0. Extensions
-- ---------------------------------------------------------------------------
create extension if not exists "pgcrypto";      -- gen_random_uuid(), digest()
create extension if not exists "uuid-ossp";

-- ---------------------------------------------------------------------------
-- 1. Enums
-- ---------------------------------------------------------------------------
do $$ begin
  create type review_state as enum (
    'listening','processing','draft','in_review','edited',
    'approved','finalized','escalation_required');
exception when duplicate_object then null; end $$;

do $$ begin
  create type app_role as enum ('doctor','scribe','admin','auditor');
exception when duplicate_object then null; end $$;

-- Conversation classification (Goal 1)
do $$ begin
  create type conversation_kind as enum (
    'single_speaker','doctor_patient','doctor_parent','doctor_spouse',
    'doctor_guardian','doctor_translator','multi_family','telemedicine_group','unknown');
exception when duplicate_object then null; end $$;

-- Relationship of a speaker to the referenced patient (Goal 1)
do $$ begin
  create type speaker_relationship as enum (
    'self','parent','spouse','child','sibling','guardian','caregiver',
    'translator','clinician','nurse','other','unknown');
exception when duplicate_object then null; end $$;

-- Clinical role on the timeline (extends SpeakerRole; Goal 6)
do $$ begin
  create type speaker_role as enum (
    'doctor','patient','caregiver','nurse','translator','other','unknown');
exception when duplicate_object then null; end $$;

-- Real-time vs Batch (Goals 3/5/8/10)
do $$ begin
  create type inference_mode as enum ('realtime','batch','auto_realtime','auto_batch','hybrid');
exception when duplicate_object then null; end $$;

-- Doctor review verdict (Goal 7)
do $$ begin
  create type review_rating as enum ('helpful','needs_improvement');
exception when duplicate_object then null; end $$;

-- Structured error categories (Goals 7/8)
do $$ begin
  create type error_category as enum (
    'wrong_patient_identified','wrong_speaker_assignment','incorrect_soap_summary',
    'medication_extraction_error','timeline_error','prompt_misunderstanding',
    'missing_diagnosis','hallucination','other');
exception when duplicate_object then null; end $$;

-- Admin workflow (Goal 8)
do $$ begin
  create type admin_status as enum ('pending','approved','rejected','resolved');
exception when duplicate_object then null; end $$;

-- Improvement pipeline stages (Goal 9)
do $$ begin
  create type improvement_stage as enum (
    'issue_classification','prompt_evaluation','regression_test_generation',
    'prompt_optimization','offline_validation','human_approval','deployed','rejected');
exception when duplicate_object then null; end $$;

-- Prescription / rendered document lifecycle (prescription preview feature)
do $$ begin
  create type document_status as enum ('draft','previewed','edited','approved','signed','voided');
exception when duplicate_object then null; end $$;

-- ---------------------------------------------------------------------------
-- 2. updated_at trigger helper
-- ---------------------------------------------------------------------------
create or replace function set_updated_at() returns trigger
language plpgsql as $$
begin new.updated_at = now(); return new; end $$;

-- ---------------------------------------------------------------------------
-- 3. Tenancy: hospitals + user profiles
-- ---------------------------------------------------------------------------
create table if not exists hospitals (
  id          uuid primary key default gen_random_uuid(),
  slug        text unique not null,
  name        text not null,
  region      text default 'asia-south1',
  -- Branding for hospital-templated documents (logo, address, regn no, footer...)
  branding    jsonb not null default '{}'::jsonb,
  active       boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create trigger trg_hospitals_updated before update on hospitals
  for each row execute function set_updated_at();

-- One row per Supabase auth user. auth.users is managed by Supabase Auth.
create table if not exists profiles (
  id           uuid primary key references auth.users(id) on delete cascade,
  hospital_id  uuid references hospitals(id) on delete set null,
  full_name    text,
  role         app_role not null default 'doctor',
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create index if not exists idx_profiles_hospital on profiles(hospital_id);
create trigger trg_profiles_updated before update on profiles
  for each row execute function set_updated_at();

-- Helper functions used by RLS policies (security definer reads the caller's profile).
create or replace function current_hospital_id() returns uuid
language sql stable security definer set search_path = public as $$
  select hospital_id from profiles where id = auth.uid();
$$;

create or replace function current_app_role() returns app_role
language sql stable security definer set search_path = public as $$
  select role from profiles where id = auth.uid();
$$;

-- ---------------------------------------------------------------------------
-- 4. Templates (mirror app/schemas/template.TemplateDefinition; versioned)
-- ---------------------------------------------------------------------------
create table if not exists templates (
  id           uuid primary key default gen_random_uuid(),
  hospital_id  uuid references hospitals(id) on delete cascade,
  template_id  text not null,                 -- e.g. 'ent', 'soap'
  version      int  not null default 1,
  name         text not null,
  description  text,
  definition   jsonb not null,                -- full TemplateDefinition JSON
  active       boolean not null default true,
  created_by   uuid references auth.users(id),
  created_at   timestamptz not null default now(),
  unique (hospital_id, template_id, version)  -- immutable per version
);
create index if not exists idx_templates_hospital on templates(hospital_id);

-- Hospital-branded printable documents (PRESCRIPTION PREVIEW feature).
-- You supply the HTML/CSS design; {{placeholders}} are filled at render time with
-- DOCTOR-CONFIRMED content only (never AI-authored Rx). Versioned + immutable.
create table if not exists document_templates (
  id            uuid primary key default gen_random_uuid(),
  hospital_id   uuid references hospitals(id) on delete cascade,
  doc_type      text not null default 'prescription',  -- prescription | referral | certificate | summary
  name          text not null,
  version       int  not null default 1,
  html          text not null,                          -- your hospital design w/ {{placeholders}}
  css           text default '',
  placeholders  jsonb not null default '[]'::jsonb,      -- declared fields the HTML expects
  active        boolean not null default true,
  created_by    uuid references auth.users(id),
  created_at    timestamptz not null default now(),
  unique (hospital_id, doc_type, name, version)
);
create index if not exists idx_doctmpl_hospital on document_templates(hospital_id, doc_type);

-- ---------------------------------------------------------------------------
-- 5. Consultations (sessions) — metadata queryable; PHI in *_enc blobs
-- ---------------------------------------------------------------------------
create table if not exists consultations (
  id                 uuid primary key default gen_random_uuid(),
  session_id         text unique not null,        -- matches app ConsultationSession.session_id
  hospital_id        uuid references hospitals(id) on delete restrict,
  practitioner_id    uuid references auth.users(id),
  patient_ref        text,                         -- tokenized / MRN reference, NOT a name
  template_id        text,
  template_version   int,
  state              review_state not null default 'listening',

  -- Intelligence layer (Goals 1-4) — non-PHI signals
  conversation_kind  conversation_kind not null default 'unknown',
  complexity_score   numeric(4,3),                 -- 0..1
  is_complex         boolean not null default false,
  inference_mode     inference_mode not null default 'realtime',
  auto_mode          boolean not null default false,
  speaker_count      int default 0,
  audio_confidence   numeric(4,3),                 -- diarization/ASR confidence 0..1
  confidence_band    text,                         -- 'high' | 'moderate' | 'low'
  referenced_patient text,                          -- e.g. 'son' (relationship resolution result)

  -- Versioning (Goal 10)
  model_version      text,
  prompt_version     text,

  -- Sign-off (mirrors ConsultationSession)
  signed_by_name     text,
  signed_at          timestamptz,
  -- signature_image is PHI-adjacent; keep in result_enc, not here.

  -- Encrypted PHI payloads (AES-GCM, app-side). NULL until produced.
  session_enc        text,    -- ConsultationSession JSON (incl. signature_image)
  result_enc         text,    -- PipelineResult JSON (raw/clean/extraction/note/risk)

  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);
create index if not exists idx_consult_hospital on consultations(hospital_id);
create index if not exists idx_consult_state on consultations(state);
create index if not exists idx_consult_practitioner on consultations(practitioner_id);
create index if not exists idx_consult_created on consultations(created_at desc);
create trigger trg_consult_updated before update on consultations
  for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- 6. Speaker timeline + relationship resolution (Goals 1 & 6)
--    Text is PHI -> store the spoken text encrypted; keep roles/relationships plain.
-- ---------------------------------------------------------------------------
create table if not exists speaker_segments (
  id                 uuid primary key default gen_random_uuid(),
  consultation_id    uuid not null references consultations(id) on delete cascade,
  segment_id         text not null,                 -- 'seg-0001'
  ordinal            int not null,
  diarized_label     text,                          -- raw 'speaker_0'
  role               speaker_role not null default 'unknown',
  relationship       speaker_relationship not null default 'unknown',
  subject_patient    text,                          -- WHO this utterance is about
  confidence         numeric(4,3),
  text_enc           text,                          -- encrypted utterance text (PHI)
  start_ms           int default 0,
  end_ms             int default 0,
  -- Doctor correction (Goal 6) — corrections re-render the note
  corrected_role     speaker_role,
  corrected_by       uuid references auth.users(id),
  corrected_at       timestamptz,
  created_at         timestamptz not null default now(),
  unique (consultation_id, segment_id)
);
create index if not exists idx_segments_consult on speaker_segments(consultation_id, ordinal);

-- ---------------------------------------------------------------------------
-- 7. Doctor consultation reviews (Goal 7)
-- ---------------------------------------------------------------------------
create table if not exists consultation_reviews (
  id                 uuid primary key default gen_random_uuid(),
  consultation_id    uuid not null references consultations(id) on delete cascade,
  hospital_id        uuid references hospitals(id) on delete set null,
  reviewer_id        uuid references auth.users(id),
  rating             review_rating not null,
  error_categories   error_category[] not null default '{}',
  comment            text,
  -- Snapshot of context at review time (for the admin console / analytics)
  model_version      text,
  prompt_version     text,
  inference_mode     inference_mode,
  audio_confidence   numeric(4,3),
  speaker_count      int,
  created_at         timestamptz not null default now()
);
create index if not exists idx_reviews_consult on consultation_reviews(consultation_id);
create index if not exists idx_reviews_rating on consultation_reviews(rating);
create index if not exists idx_reviews_errcat on consultation_reviews using gin (error_categories);

-- ---------------------------------------------------------------------------
-- 8. Admin review console queue (Goal 8)
-- ---------------------------------------------------------------------------
create table if not exists admin_reviews (
  id              uuid primary key default gen_random_uuid(),
  review_id       uuid not null unique references consultation_reviews(id) on delete cascade,
  status          admin_status not null default 'pending',
  assigned_to     uuid references auth.users(id),
  admin_notes     text,
  resolved_at     timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index if not exists idx_adminrev_status on admin_reviews(status);
create trigger trg_adminrev_updated before update on admin_reviews
  for each row execute function set_updated_at();

-- Auto-enqueue every "needs_improvement" review into the admin queue.
create or replace function enqueue_admin_review() returns trigger
language plpgsql as $$
begin
  if new.rating = 'needs_improvement' then
    insert into admin_reviews(review_id) values (new.id)
    on conflict (review_id) do nothing;
  end if;
  return new;
end $$;
create trigger trg_enqueue_admin after insert on consultation_reviews
  for each row execute function enqueue_admin_review();

-- ---------------------------------------------------------------------------
-- 9. Prompt & model versioning (Goal 10)
-- ---------------------------------------------------------------------------
create table if not exists model_versions (
  id          uuid primary key default gen_random_uuid(),
  provider    text not null,            -- 'vertex','sarvam'
  model_id    text not null,            -- 'gemini-3.5-flash'
  label       text,
  active      boolean not null default true,
  created_at  timestamptz not null default now(),
  unique (provider, model_id)
);

create table if not exists prompt_versions (
  id              uuid primary key default gen_random_uuid(),
  name            text not null,        -- 'extract','clean','risk','combined','relationship_resolution'
  version         int  not null,
  content         text not null,
  content_hash    text generated always as (encode(digest(content,'sha256'),'hex')) stored,
  model_version   text,
  inference_mode  inference_mode,
  active          boolean not null default false,
  created_by      uuid references auth.users(id),
  created_at      timestamptz not null default now(),
  unique (name, version)
);
create index if not exists idx_prompt_active on prompt_versions(name, active);

-- ---------------------------------------------------------------------------
-- 10. Continuous improvement pipeline (Goal 9)
-- ---------------------------------------------------------------------------
create table if not exists improvement_items (
  id                 uuid primary key default gen_random_uuid(),
  admin_review_id    uuid references admin_reviews(id) on delete set null,
  error_category     error_category,
  stage              improvement_stage not null default 'issue_classification',
  prompt_name        text,                       -- which prompt this targets
  candidate_prompt   text,                       -- proposed new prompt text (offline only)
  regression_test_id text,                       -- pointer to generated test case
  eval_results       jsonb default '{}'::jsonb,
  approved_by        uuid references auth.users(id),
  deployed_prompt_version_id uuid references prompt_versions(id),
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);
create index if not exists idx_improve_stage on improvement_items(stage);
create trigger trg_improve_updated before update on improvement_items
  for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- 11. Prescription / rendered documents (prescription preview feature)
--     rendered_html / edited_html contain patient data -> PHI -> store encrypted.
-- ---------------------------------------------------------------------------
create table if not exists rendered_documents (
  id                   uuid primary key default gen_random_uuid(),
  consultation_id      uuid not null references consultations(id) on delete cascade,
  document_template_id uuid references document_templates(id) on delete set null,
  doc_type             text not null default 'prescription',
  status               document_status not null default 'draft',
  rendered_html_enc    text,             -- AI/template-filled draft (encrypted PHI)
  edited_html_enc      text,             -- doctor's edited version (encrypted PHI)
  approved_by          uuid references auth.users(id),
  approved_at          timestamptz,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);
create index if not exists idx_rendered_consult on rendered_documents(consultation_id);
create trigger trg_rendered_updated before update on rendered_documents
  for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- 12. AI consultation editor history (Goal 11) — undo/redo via sequence
--     before/after content is PHI -> encrypted.
-- ---------------------------------------------------------------------------
create table if not exists consultation_edits (
  id              uuid primary key default gen_random_uuid(),
  consultation_id uuid not null references consultations(id) on delete cascade,
  seq             int not null,                 -- monotonically increasing per consultation
  instruction     text,                          -- natural-language edit request
  target_section  text,
  before_enc      text,                          -- encrypted prior content
  after_enc       text,                          -- encrypted new content
  applied         boolean not null default false,
  undone          boolean not null default false,
  created_by      uuid references auth.users(id),
  created_at      timestamptz not null default now(),
  unique (consultation_id, seq)
);
create index if not exists idx_edits_consult on consultation_edits(consultation_id, seq);

-- ---------------------------------------------------------------------------
-- 13. Feature flags (Goal 13)
-- ---------------------------------------------------------------------------
create table if not exists feature_flags (
  key          text not null,
  hospital_id  uuid references hospitals(id) on delete cascade,  -- NULL = global
  enabled      boolean not null default false,
  value        jsonb not null default '{}'::jsonb,
  updated_at   timestamptz not null default now(),
  primary key (key, hospital_id)
);

-- ---------------------------------------------------------------------------
-- 14. Telemetry / latency (Goals 4, 12, 13)
-- ---------------------------------------------------------------------------
create table if not exists stage_latencies (
  id              uuid primary key default gen_random_uuid(),
  consultation_id uuid references consultations(id) on delete cascade,
  stage           text not null,                -- 'stt','clean','extract','risk','note','diarize'
  inference_mode  inference_mode,
  model_version   text,
  latency_ms      int not null,
  created_at      timestamptz not null default now()
);
create index if not exists idx_latency_stage on stage_latencies(stage, created_at desc);

-- ---------------------------------------------------------------------------
-- 15. Append-only audit with SHA-256 hash chain (mirrors security/audit.py)
-- ---------------------------------------------------------------------------
create table if not exists audit_events (
  id            bigserial primary key,
  actor_id      text not null,
  action        text not null,
  resource      text not null,
  session_id    text,
  hospital_id   uuid references hospitals(id) on delete set null,
  phi_accessed  boolean not null default false,
  detail        text,
  prev_hash     text,                            -- hash of previous row (set app-side)
  hash          text,                            -- sha256(record + prev_hash) (set app-side)
  created_at    timestamptz not null default now()
);
create index if not exists idx_audit_session on audit_events(session_id);
create index if not exists idx_audit_created on audit_events(created_at);
-- Append-only: block UPDATE/DELETE for everyone except superuser/service maintenance.
create rule audit_no_update as on update to audit_events do instead nothing;
create rule audit_no_delete as on delete to audit_events do instead nothing;

-- ============================================================================
-- 16. ROW LEVEL SECURITY
--   - service_role bypasses RLS (server-side trusted key only).
--   - authenticated users are scoped to their own hospital.
--   - admins/auditors get hospital-wide read on review/audit tables.
-- ============================================================================
alter table hospitals             enable row level security;
alter table profiles              enable row level security;
alter table templates             enable row level security;
alter table document_templates    enable row level security;
alter table consultations         enable row level security;
alter table speaker_segments      enable row level security;
alter table consultation_reviews  enable row level security;
alter table admin_reviews         enable row level security;
alter table model_versions        enable row level security;
alter table prompt_versions       enable row level security;
alter table improvement_items     enable row level security;
alter table rendered_documents    enable row level security;
alter table consultation_edits    enable row level security;
alter table feature_flags         enable row level security;
alter table stage_latencies       enable row level security;
alter table audit_events          enable row level security;

-- Profiles: a user can read/update only their own row.
create policy profiles_self_select on profiles for select using (id = auth.uid());
create policy profiles_self_update on profiles for update using (id = auth.uid());

-- Hospitals: members can read their hospital.
create policy hospitals_member_select on hospitals for select
  using (id = current_hospital_id());

-- Generic "same hospital" read/write for tenant-scoped tables.
create policy templates_tenant on templates for all
  using (hospital_id = current_hospital_id())
  with check (hospital_id = current_hospital_id());

create policy doctmpl_tenant on document_templates for all
  using (hospital_id = current_hospital_id())
  with check (hospital_id = current_hospital_id());

create policy consult_tenant on consultations for all
  using (hospital_id = current_hospital_id())
  with check (hospital_id = current_hospital_id());

create policy segments_tenant on speaker_segments for all
  using (exists (select 1 from consultations c
                 where c.id = consultation_id and c.hospital_id = current_hospital_id()))
  with check (exists (select 1 from consultations c
                 where c.id = consultation_id and c.hospital_id = current_hospital_id()));

create policy reviews_tenant on consultation_reviews for all
  using (hospital_id = current_hospital_id())
  with check (hospital_id = current_hospital_id());

create policy rendered_tenant on rendered_documents for all
  using (exists (select 1 from consultations c
                 where c.id = consultation_id and c.hospital_id = current_hospital_id()))
  with check (exists (select 1 from consultations c
                 where c.id = consultation_id and c.hospital_id = current_hospital_id()));

create policy edits_tenant on consultation_edits for all
  using (exists (select 1 from consultations c
                 where c.id = consultation_id and c.hospital_id = current_hospital_id()))
  with check (exists (select 1 from consultations c
                 where c.id = consultation_id and c.hospital_id = current_hospital_id()));

-- Admin review queue: only admins/auditors of the hospital.
create policy adminrev_admin on admin_reviews for all
  using (current_app_role() in ('admin','auditor')
         and exists (select 1 from consultation_reviews r
                     where r.id = review_id and r.hospital_id = current_hospital_id()))
  with check (current_app_role() = 'admin');

create policy improve_admin on improvement_items for all
  using (current_app_role() in ('admin','auditor'))
  with check (current_app_role() = 'admin');

-- Prompt/model versions: admins manage; everyone in tenant can read active.
create policy prompts_admin_all on prompt_versions for all
  using (current_app_role() = 'admin') with check (current_app_role() = 'admin');
create policy prompts_read on prompt_versions for select using (true);
create policy models_read on model_versions for select using (true);
create policy models_admin on model_versions for all
  using (current_app_role() = 'admin') with check (current_app_role() = 'admin');

-- Feature flags: global (NULL hospital) readable by all; hospital flags by members.
create policy flags_read on feature_flags for select
  using (hospital_id is null or hospital_id = current_hospital_id());
create policy flags_admin on feature_flags for all
  using (current_app_role() = 'admin') with check (current_app_role() = 'admin');

-- Telemetry: writable by tenant, readable by admin/auditor.
create policy latency_tenant on stage_latencies for all
  using (exists (select 1 from consultations c
                 where c.id = consultation_id and c.hospital_id = current_hospital_id()))
  with check (exists (select 1 from consultations c
                 where c.id = consultation_id and c.hospital_id = current_hospital_id()));

-- Audit: insert by tenant members; read by admin/auditor; no update/delete (rules above).
create policy audit_insert on audit_events for insert
  with check (hospital_id = current_hospital_id() or hospital_id is null);
create policy audit_read on audit_events for select
  using (current_app_role() in ('admin','auditor') and hospital_id = current_hospital_id());

-- ============================================================================
-- 17. Seed (optional) — one demo hospital + a doctor profile placeholder.
--   Replace the auth uid after you create the user in Supabase Auth.
-- ============================================================================
insert into hospitals (slug, name, region, branding)
values ('demo-hospital','Demo Hospital','asia-south1',
        '{"address":"","logo_url":"","registration_no":"","footer":""}'::jsonb)
on conflict (slug) do nothing;

-- After creating an auth user, link them:
--   insert into profiles (id, hospital_id, full_name, role)
--   values ('<auth-user-uuid>', (select id from hospitals where slug='demo-hospital'),
--           'Dr. Demo', 'doctor');
