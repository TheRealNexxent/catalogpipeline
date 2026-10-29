-- Audio Refinery: Table 1 (staging), Table 2 (curated), approval changesets and releases.
-- Nothing is ever deleted: Table 1 is append-only, Table 2 rows are superseded, releases are immutable.

CREATE TABLE IF NOT EXISTS partners (
  id serial PRIMARY KEY,
  name text UNIQUE NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runs (
  id serial PRIMARY KEY,
  partner_id int NOT NULL REFERENCES partners(id),
  source text NOT NULL,
  machine jsonb NOT NULL DEFAULT '{}',
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  files int NOT NULL DEFAULT 0,
  inserted int NOT NULL DEFAULT 0,
  seen_again int NOT NULL DEFAULT 0
);

-- TABLE 1: every observation, repeats included. A rescan of an unchanged file only bumps last_seen.
CREATE TABLE IF NOT EXISTS audio_catalog (
  id bigserial PRIMARY KEY,
  run_id int NOT NULL REFERENCES runs(id),
  partner_id int NOT NULL REFERENCES partners(id),
  source_path text NOT NULL,
  file_sha256 text,
  pcm_sha256 text,
  versions_hash text NOT NULL,              -- hash of the step versions that produced the measurements
  bundle_id text,
  bundle_role text,
  route text NOT NULL,
  status text NOT NULL CHECK (status IN ('ok', 'gate_failed', 'missing')),
  gates_failed text[] NOT NULL DEFAULT '{}',
  duration_s real,
  sample_rate int,
  channels int,
  codec text,
  content_class text,
  language text,
  snr_db real,
  speech_ratio_pct real,
  quality_pq real,
  pii_count int,
  pii_verified boolean,
  ai_generated_score real,
  step_coverage real,
  measurements jsonb NOT NULL,
  declared jsonb NOT NULL DEFAULT '{}',
  fingerprint bytea,
  first_seen timestamptz NOT NULL DEFAULT now(),
  last_seen timestamptz NOT NULL DEFAULT now(),
  UNIQUE (partner_id, source_path, file_sha256, versions_hash)
);
CREATE INDEX IF NOT EXISTS audio_catalog_pcm ON audio_catalog (pcm_sha256);
CREATE INDEX IF NOT EXISTS audio_catalog_path ON audio_catalog (partner_id, source_path);

CREATE TABLE IF NOT EXISTS profiles (
  name text NOT NULL,
  version int NOT NULL,
  config jsonb NOT NULL,
  PRIMARY KEY (name, version)
);

-- The approval layer: a proposed set of Table 2 changes. Nothing reaches Table 2 until it is applied.
CREATE TABLE IF NOT EXISTS changesets (
  id serial PRIMARY KEY,
  profile text NOT NULL,
  profile_version int NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'applied', 'discarded')),
  note text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  applied_at timestamptz
);

CREATE TABLE IF NOT EXISTS changeset_items (
  id bigserial PRIMARY KEY,
  changeset_id int NOT NULL REFERENCES changesets(id),
  catalog_id bigint NOT NULL REFERENCES audio_catalog(id),
  proposal text NOT NULL CHECK (proposal IN ('insert', 'update', 'skip', 'review', 'exclude')),
  case_code text,                            -- E1..E14 from Baseline.md section 10.3
  reason text NOT NULL,
  default_decision text NOT NULL CHECK (default_decision IN ('accept', 'reject')),
  related_curated_id bigint,
  tier text NOT NULL,
  quality real,
  coverage real,
  scoring jsonb NOT NULL,
  decision text CHECK (decision IN ('accept', 'reject')),
  decided_at timestamptz
);

-- TABLE 2: approved data only. One current row per recording (valid_to IS NULL).
CREATE TABLE IF NOT EXISTS audio_curated (
  id bigserial PRIMARY KEY,
  catalog_id bigint NOT NULL REFERENCES audio_catalog(id),
  changeset_id int NOT NULL REFERENCES changesets(id),
  partner_id int NOT NULL REFERENCES partners(id),
  source_path text NOT NULL,
  pcm_sha256 text NOT NULL,
  file_sha256 text,
  profile text NOT NULL,
  profile_version int NOT NULL,
  tier text NOT NULL,
  quality real,
  coverage real,
  labels jsonb NOT NULL DEFAULT '{}',
  derivatives jsonb NOT NULL DEFAULT '{}',
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to timestamptz,
  superseded_by bigint REFERENCES audio_curated(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS audio_curated_current ON audio_curated (pcm_sha256) WHERE valid_to IS NULL;

CREATE TABLE IF NOT EXISTS releases (
  id serial PRIMARY KEY,
  version int UNIQUE NOT NULL,
  changeset_id int REFERENCES changesets(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  item_count int NOT NULL,
  manifest jsonb NOT NULL,
  manifest_sha256 text NOT NULL
);
