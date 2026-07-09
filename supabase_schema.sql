-- Run this once in your Supabase project: Dashboard -> SQL Editor -> New query
-- -> paste this whole file -> Run.
--
-- This replaces backend/jobs.py's in-memory dict + job.json-snapshot-per-folder
-- approach with a real table, scoped to whichever user created each job. The
-- pipeline itself is untouched - each job still gets its own jobs/<job_id>/
-- folder on disk for the actual video/events.json/etc; this table only tracks
-- ownership + status metadata, which is what the in-memory dict used to hold.

create table if not exists public.jobs (
  job_id             text primary key,
  user_id            uuid not null references auth.users(id) on delete cascade,
  dir                text not null,          -- server-side folder path, e.g. jobs/<job_id>
  status             text not null default 'queued',   -- queued | running | done | failed
  step               text not null default 'queued',
  step_index         int not null default 0,
  total_steps        int not null default 0,
  game               text not null default 'pokemon',
  mode               text not null default 'doubles',
  source_type        text,                   -- 'url' | 'upload' | 'seed' | 'showdown'
  url                text,
  video              text,
  player             text,                   -- source_type='showdown' only: which side is "you"
                                              -- (a Showdown username, or 'p1'/'p2')
  regulation         text not null default 'm-b',  -- which Pokemon Champions regulation's
                                              -- roster/legal-mechanics data was enforced for
                                              -- this job - see adapters/pokemon/regulations/*.json
  matches_found      int,
  cost_estimate_usd  numeric,
  error              text,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

-- If you ran this script before the "player" column existed (added for the
-- Showdown replay source_type), `create table if not exists` above won't add
-- it retroactively - this does, and is a no-op if it's already there.
alter table public.jobs add column if not exists player text;

-- Same story for "regulation" (added for the format/regulation selector
-- feature) - this table's CREATE was never re-run after that column was
-- added to backend/jobs.py's row dict, so any project created before this
-- fix is missing it. This is a no-op if the column already exists.
alter table public.jobs add column if not exists regulation text not null default 'm-b';

-- Keep updated_at current on every write (handy for "processing... how long
-- has it been" UI later, and for debugging).
create or replace function public.set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists jobs_set_updated_at on public.jobs;
create trigger jobs_set_updated_at
  before update on public.jobs
  for each row execute function public.set_updated_at();

-- Row Level Security: defense-in-depth. The FastAPI backend uses the
-- service_role key (which bypasses RLS) and enforces "only your own jobs" in
-- application code (every jobs.py function takes/filters by user_id from the
-- verified JWT - see backend/auth.py). RLS matters if anything ever queries
-- Supabase directly from the frontend with the anon key instead of going
-- through the backend - these policies make sure that path is safe too.
alter table public.jobs enable row level security;

drop policy if exists "select own jobs" on public.jobs;
create policy "select own jobs" on public.jobs
  for select using (auth.uid() = user_id);

drop policy if exists "insert own jobs" on public.jobs;
create policy "insert own jobs" on public.jobs
  for insert with check (auth.uid() = user_id);

drop policy if exists "update own jobs" on public.jobs;
create policy "update own jobs" on public.jobs
  for update using (auth.uid() = user_id);

drop policy if exists "delete own jobs" on public.jobs;
create policy "delete own jobs" on public.jobs
  for delete using (auth.uid() = user_id);

create index if not exists jobs_user_id_idx on public.jobs(user_id);

-- ---------------------------------------------------------------------------
-- Internal audit log (backend/audit.py) - NOT user-facing. No API endpoint
-- ever reads this table; it exists for internal review (debugging accuracy
-- issues, understanding real usage over time), separately from the per-job
-- `jobs` table above. Freeform payload (jsonb) rather than fixed columns, so
-- a new kind of event to log never needs its own migration.
create table if not exists public.audit_log (
  id           text primary key,
  event_type   text not null,       -- e.g. job_created | job_step | job_completed | job_failed | event_corrected
  created_at   double precision not null,   -- unix seconds, matches backend/audit.py's time.time()
  payload      jsonb
);

-- RLS enabled with NO select/insert/update/delete policy for anon or
-- authenticated roles at all - only the service_role key (used exclusively
-- server-side in backend/audit.py, never sent to the frontend) can touch
-- this table. Even a leaked anon key could never read or forge an entry.
alter table public.audit_log enable row level security;

create index if not exists audit_log_event_type_idx on public.audit_log(event_type);
create index if not exists audit_log_created_at_idx on public.audit_log(created_at);

-- ---------------------------------------------------------------------------
-- Coach sharing (backend/coaching.py) - player-generated shareable links, a
-- persistent coach/student roster, and coaching notes. See that module's own
-- docstring for the full privacy model: every account is private by default;
-- the ONLY way another account ever sees anything here is a valid,
-- non-revoked, non-expired token the PLAYER themselves generated. As with
-- every other table in this file, the FastAPI backend uses the service_role
-- key (bypasses RLS) and enforces ownership in application code - these
-- policies are defense-in-depth for direct client-side Supabase access,
-- which this app doesn't currently do for any table.

create table if not exists public.share_links (
  token             text primary key,
  owner_user_id     uuid not null references auth.users(id) on delete cascade,
  label             text,              -- the PLAYER's own private note about this link - never
                                        -- shown to whoever holds it (see coaching.py's add_student)
  expires_at        timestamptz,       -- null = never expires (player's own choice per link)
  revoked_at        timestamptz,
  created_at        timestamptz not null default now(),
  last_viewed_at    timestamptz
);

alter table public.share_links enable row level security;

drop policy if exists "select own share links" on public.share_links;
create policy "select own share links" on public.share_links
  for select using (auth.uid() = owner_user_id);

drop policy if exists "insert own share links" on public.share_links;
create policy "insert own share links" on public.share_links
  for insert with check (auth.uid() = owner_user_id);

drop policy if exists "update own share links" on public.share_links;
create policy "update own share links" on public.share_links
  for update using (auth.uid() = owner_user_id);

drop policy if exists "delete own share links" on public.share_links;
create policy "delete own share links" on public.share_links
  for delete using (auth.uid() = owner_user_id);

create index if not exists share_links_owner_idx on public.share_links(owner_user_id);

create table if not exists public.coach_student_links (
  id                text primary key,
  coach_user_id     uuid not null references auth.users(id) on delete cascade,
  player_user_id    uuid not null references auth.users(id) on delete cascade,
  share_token       text references public.share_links(token) on delete set null,
  coach_label       text,              -- the COACH's own nickname for this student - independent
                                        -- of share_links.label (see coaching.add_student's docstring)
  added_at          timestamptz not null default now(),
  unique (coach_user_id, player_user_id)
);

alter table public.coach_student_links enable row level security;

drop policy if exists "coach manages own roster" on public.coach_student_links;
create policy "coach manages own roster" on public.coach_student_links
  for all using (auth.uid() = coach_user_id) with check (auth.uid() = coach_user_id);

create index if not exists coach_student_links_coach_idx on public.coach_student_links(coach_user_id);
create index if not exists coach_student_links_player_idx on public.coach_student_links(player_user_id);

create table if not exists public.coach_notes (
  id                text primary key,
  coach_user_id     uuid not null references auth.users(id) on delete cascade,
  player_user_id    uuid not null references auth.users(id) on delete cascade,
  coach_email       text,              -- denormalized at write time - see coaching.add_note's docstring
                                        -- for why (no general "look up any account's email" capability)
  text              text not null,
  category          text,              -- freeform, e.g. "general" | "coaching_plan" | "skill_focus"
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

alter table public.coach_notes enable row level security;

-- A coach manages (writes/edits/deletes) only their own notes...
drop policy if exists "coach manages own notes" on public.coach_notes;
create policy "coach manages own notes" on public.coach_notes
  for all using (auth.uid() = coach_user_id) with check (auth.uid() = coach_user_id);

-- ...but the PLAYER a note is about can also read it (GET /account/coaching-notes -
-- the player's own "what has any coach said about me" view, the whole point
-- of this feature per the "100% maybe even..." scoping decision).
drop policy if exists "player reads notes about them" on public.coach_notes;
create policy "player reads notes about them" on public.coach_notes
  for select using (auth.uid() = player_user_id);

create index if not exists coach_notes_coach_player_idx on public.coach_notes(coach_user_id, player_user_id);
create index if not exists coach_notes_player_idx on public.coach_notes(player_user_id);
