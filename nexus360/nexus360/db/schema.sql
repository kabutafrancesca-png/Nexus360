-- =====================================================================
-- Infratel Nexus 360  |  PostgreSQL / Supabase schema  (source of truth)
-- Run in Supabase: SQL Editor > paste > Run.   Locally: psql $DATABASE_URL -f db/schema.sql
-- Later changes go in db/migrations/NNN_description.sql (never edit applied tables silently).
-- =====================================================================
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "pg_trgm";    -- fuzzy / text search

-- ---------- ENUMS ----------
CREATE TYPE user_role        AS ENUM ('sales_rep','account_manager','sales_manager','noc_liaison','executive','admin');
CREATE TYPE account_status   AS ENUM ('active','at_risk','renewal_due','expansion_ready','churned');
CREATE TYPE account_tier     AS ENUM ('standard','strategic','key');
CREATE TYPE decision_role    AS ENUM ('economic_buyer','technical_evaluator','champion','influencer','blocker','user');
CREATE TYPE sentiment        AS ENUM ('positive','neutral','negative');
CREATE TYPE lead_status      AS ENUM ('new','contacted','qualified','disqualified','converted');
CREATE TYPE opp_stage        AS ENUM ('qualification','discovery','proposal','negotiation','contract_review','closed_won','closed_lost');
CREATE TYPE maturity_tier    AS ENUM ('bronze','silver','gold','platinum');
CREATE TYPE engagement_type  AS ENUM ('dc_tour','solution_demo','event','meeting','call','email','executive_briefing');
CREATE TYPE task_status      AS ENUM ('open','in_progress','done','overdue');
CREATE TYPE rec_status       AS ENUM ('suggested','accepted','dismissed','converted');
CREATE TYPE contract_type    AS ENUM ('msa','sla','addendum','nda');
CREATE TYPE contract_status  AS ENUM ('draft','in_review','pending_signature','active','expired','terminated','renewed');
CREATE TYPE signature_status AS ENUM ('pending','signed','declined','expired');
CREATE TYPE comm_channel     AS ENUM ('email','sms','call');
CREATE TYPE data_class       AS ENUM ('public','internal','pii','commercially_sensitive');

-- ---------- COMMON: updated_at trigger ----------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END; $$ LANGUAGE plpgsql;

-- =====================================================================
-- CORE / SECURITY
-- =====================================================================
CREATE TABLE users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email         TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  full_name     TEXT NOT NULL,
  role          user_role NOT NULL DEFAULT 'sales_rep',
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE audit_logs (            -- append-only: never UPDATE/DELETE from app code
  id          BIGSERIAL PRIMARY KEY,
  user_id     UUID REFERENCES users(id),
  action      TEXT NOT NULL,         -- view | create | update | delete | login ...
  entity_type TEXT NOT NULL,
  entity_id   TEXT,
  changes     JSONB NOT NULL DEFAULT '{}',
  ip_address  TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_entity ON audit_logs(entity_type, entity_id);
CREATE INDEX idx_audit_user   ON audit_logs(user_id, created_at DESC);

CREATE TABLE notifications (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title      TEXT NOT NULL,
  body       TEXT,
  link       TEXT,
  is_read    BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =====================================================================
-- MODULE 1: CIMS  (accounts, contacts, products)
-- =====================================================================
CREATE TABLE verticals (
  id   SERIAL PRIMARY KEY,
  name TEXT UNIQUE NOT NULL          -- Telecommunications, Mining, Banking & Fintech, Government, Retail & FMCG, Healthcare
);

CREATE TABLE products (
  id       SERIAL PRIMARY KEY,
  name     TEXT UNIQUE NOT NULL,     -- Colocation, Cloud Compute, Internet Connectivity, DRaaS, SD-WAN ...
  category TEXT,
  list_price NUMERIC(14,2)
);

CREATE TABLE accounts (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_name      TEXT NOT NULL,
  vertical_id       INT REFERENCES verticals(id),
  parent_account_id UUID REFERENCES accounts(id),      -- subsidiaries / account map
  tier              account_tier NOT NULL DEFAULT 'standard',
  region            TEXT,
  country           TEXT DEFAULT 'Zambia',
  website           TEXT,
  annual_revenue    NUMERIC(16,2),                      -- customer's size
  contracted_revenue NUMERIC(16,2) NOT NULL DEFAULT 0,  -- what they pay Infratel (ARR)
  status            account_status NOT NULL DEFAULT 'active',
  health_score      INT CHECK (health_score BETWEEN 0 AND 100) DEFAULT 70,
  strategic_score   NUMERIC(5,2) DEFAULT 0,             -- VSI top-account ranking
  data_class        data_class NOT NULL DEFAULT 'internal',
  owner_id          UUID REFERENCES users(id),          -- account manager
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_accounts_vertical ON accounts(vertical_id);
CREATE INDEX idx_accounts_owner    ON accounts(owner_id);
CREATE INDEX idx_accounts_name_trgm ON accounts USING gin (company_name gin_trgm_ops);
CREATE TRIGGER trg_accounts_upd BEFORE UPDATE ON accounts FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE contacts (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id       UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  reports_to_id    UUID REFERENCES contacts(id),        -- contact hierarchy
  full_name        TEXT NOT NULL,
  job_title        TEXT,
  email            TEXT,
  phone            TEXT,
  decision_role    decision_role NOT NULL DEFAULT 'user',  -- buying committee node
  seniority        TEXT,                                   -- c_suite | director | manager | staff
  sentiment        sentiment NOT NULL DEFAULT 'neutral',
  last_interaction_at TIMESTAMPTZ,
  data_class       data_class NOT NULL DEFAULT 'pii',
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_contacts_account ON contacts(account_id);
CREATE TRIGGER trg_contacts_upd BEFORE UPDATE ON contacts FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Services the customer currently consumes (drives cross-sell)
CREATE TABLE account_services (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id     UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  product_id     INT  NOT NULL REFERENCES products(id),
  monthly_value  NUMERIC(14,2) NOT NULL DEFAULT 0,
  started_on     DATE,
  is_active      BOOLEAN NOT NULL DEFAULT TRUE,
  UNIQUE (account_id, product_id)
);

-- =====================================================================
-- MODULE 2: PIPELINE (leads vs opportunities)
-- =====================================================================
CREATE TABLE leads (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_name  TEXT NOT NULL,
  contact_name  TEXT,
  contact_email TEXT,
  contact_phone TEXT,
  vertical_id   INT REFERENCES verticals(id),
  source        TEXT,                                   -- website | referral | event | cold_outreach
  status        lead_status NOT NULL DEFAULT 'new',
  score         INT DEFAULT 0,
  owner_id      UUID REFERENCES users(id),
  converted_account_id UUID REFERENCES accounts(id),
  notes         TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_leads_upd BEFORE UPDATE ON leads FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE opportunities (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id       UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  lead_id          UUID REFERENCES leads(id),
  product_id       INT REFERENCES products(id),
  name             TEXT NOT NULL,
  stage            opp_stage NOT NULL DEFAULT 'qualification',
  maturity         maturity_tier NOT NULL DEFAULT 'bronze',
  maturity_score   INT NOT NULL DEFAULT 10,              -- 0-100, recalculated by engine
  win_probability  NUMERIC(5,2) NOT NULL DEFAULT 10,     -- % (bronze 10-20, silver 30-50, gold 60-75, platinum 80-95)
  amount           NUMERIC(14,2) NOT NULL DEFAULT 0,
  weighted_amount  NUMERIC(14,2) GENERATED ALWAYS AS (amount * win_probability / 100) STORED,
  expected_close   DATE,
  owner_id         UUID REFERENCES users(id),
  lost_reason      TEXT,
  last_activity_at TIMESTAMPTZ NOT NULL DEFAULT now(),   -- for score degradation of dormant opps
  closed_at        TIMESTAMPTZ,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_opps_account ON opportunities(account_id);
CREATE INDEX idx_opps_stage   ON opportunities(stage);
CREATE INDEX idx_opps_owner   ON opportunities(owner_id);
CREATE TRIGGER trg_opps_upd BEFORE UPDATE ON opportunities FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE opportunity_history (   -- stage / maturity changes (conversion + velocity analytics)
  id             BIGSERIAL PRIMARY KEY,
  opportunity_id UUID NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
  from_stage     opp_stage, to_stage opp_stage,
  from_maturity  maturity_tier, to_maturity maturity_tier,
  reason         TEXT,                                   -- e.g. 'dc_tour logged', 'dormant 30d'
  changed_by     UUID REFERENCES users(id),
  changed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =====================================================================
-- MODULE 3: EXPERIENTIAL JOURNEY TRACKER
-- =====================================================================
CREATE TABLE engagement_events (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id      UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  opportunity_id  UUID REFERENCES opportunities(id),
  type            engagement_type NOT NULL,
  title           TEXT,
  tour_type       TEXT,                                  -- e.g. 'Data Centre Tour', 'DR Demo'
  event_date      TIMESTAMPTZ NOT NULL,
  facilitator_id  UUID REFERENCES users(id),             -- account manager
  outcome_notes   TEXT,
  follow_up_actions TEXT,
  is_qualifying   BOOLEAN NOT NULL DEFAULT FALSE,        -- triggers maturity bump
  maturity_impact INT NOT NULL DEFAULT 0,                -- points added to maturity_score
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_events_account ON engagement_events(account_id, event_date DESC);

CREATE TABLE engagement_attendees (
  event_id   UUID NOT NULL REFERENCES engagement_events(id) ON DELETE CASCADE,
  contact_id UUID NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  PRIMARY KEY (event_id, contact_id)
);

CREATE TABLE tasks (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title          TEXT NOT NULL,
  description    TEXT,
  assigned_to    UUID REFERENCES users(id),
  account_id     UUID REFERENCES accounts(id),
  opportunity_id UUID REFERENCES opportunities(id),
  event_id       UUID REFERENCES engagement_events(id),
  due_at         TIMESTAMPTZ,
  sla_hours      INT,
  status         task_status NOT NULL DEFAULT 'open',
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at   TIMESTAMPTZ
);
CREATE INDEX idx_tasks_assignee ON tasks(assigned_to, status);

-- =====================================================================
-- MODULE 4: VSI & ABM  (uses accounts, verticals, contacts; plus:)
-- =====================================================================
CREATE TABLE sector_snapshots (      -- periodic rollup for trend / heatmap (job or on-demand)
  id               BIGSERIAL PRIMARY KEY,
  vertical_id      INT NOT NULL REFERENCES verticals(id),
  snapshot_date    DATE NOT NULL,
  revenue          NUMERIC(16,2),
  pipeline_value   NUMERIC(16,2),
  pipeline_velocity NUMERIC(8,2),
  churn_risk       NUMERIC(5,2),
  expansion_potential NUMERIC(5,2),
  UNIQUE (vertical_id, snapshot_date)
);

CREATE TABLE white_space (           -- divisions/geos inside an existing customer not yet served
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id  UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  description TEXT NOT NULL,         -- 'Kitwe division has no connectivity contract'
  est_value   NUMERIC(14,2),
  status      TEXT NOT NULL DEFAULT 'open'
);

-- =====================================================================
-- MODULE 5: CROSS-SELL / UPSELL
-- =====================================================================
CREATE TABLE usage_metrics (
  id          BIGSERIAL PRIMARY KEY,
  account_id  UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  product_id  INT  NOT NULL REFERENCES products(id),
  metric_name TEXT NOT NULL,         -- rack_utilization_pct | cpu_peak_pct | bandwidth_mbps | latency_spikes
  value       NUMERIC(14,2) NOT NULL,
  capacity    NUMERIC(14,2),
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_usage_account ON usage_metrics(account_id, product_id, recorded_at DESC);

CREATE TABLE recommendations (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id      UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  product_id      INT  NOT NULL REFERENCES products(id),     -- recommended product
  probability     NUMERIC(5,2) NOT NULL,                      -- 0-100 adoption probability
  revenue_impact  NUMERIC(14,2) NOT NULL DEFAULT 0,
  priority_score  NUMERIC(14,2) GENERATED ALWAYS AS (probability * revenue_impact / 100) STORED,
  signals         JSONB NOT NULL DEFAULT '[]',                -- transparent "why": ["rack util 85%","no DR contract"]
  status          rec_status NOT NULL DEFAULT 'suggested',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  actioned_by     UUID REFERENCES users(id),
  actioned_at     TIMESTAMPTZ
);
CREATE INDEX idx_recs_priority ON recommendations(status, priority_score DESC);

-- =====================================================================
-- MODULE 6: CONTRACTS
-- =====================================================================
CREATE TABLE contract_templates (
  id        SERIAL PRIMARY KEY,
  name      TEXT NOT NULL,
  type      contract_type NOT NULL,
  body_html TEXT NOT NULL,           -- with {{placeholders}} e.g. {{company_name}}, {{acv}}, {{sla_terms}}
  is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE contracts (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id      UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  opportunity_id  UUID REFERENCES opportunities(id),
  template_id     INT REFERENCES contract_templates(id),
  contract_number TEXT UNIQUE,
  title           TEXT NOT NULL,
  type            contract_type NOT NULL,
  status          contract_status NOT NULL DEFAULT 'draft',
  effective_date  DATE,
  expiry_date     DATE,
  annual_value    NUMERIC(14,2),                 -- ACV
  currency        TEXT NOT NULL DEFAULT 'USD',
  current_version INT NOT NULL DEFAULT 1,
  pdf_path        TEXT,                          -- Supabase Storage path or local uploads/ path
  erp_ref         TEXT,                          -- ERP billing reference
  auto_renew      BOOLEAN NOT NULL DEFAULT FALSE,
  owner_id        UUID REFERENCES users(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_contracts_expiry ON contracts(expiry_date) WHERE status = 'active';
CREATE INDEX idx_contracts_account ON contracts(account_id);
CREATE TRIGGER trg_contracts_upd BEFORE UPDATE ON contracts FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE contract_versions (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contract_id    UUID NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
  version_no     INT NOT NULL,
  body_html      TEXT,
  pdf_path       TEXT,
  change_summary TEXT,
  created_by     UUID REFERENCES users(id),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (contract_id, version_no)
);

CREATE TABLE contract_signatories (   -- e-signature workflow
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contract_id  UUID NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
  contact_id   UUID REFERENCES contacts(id),
  user_id      UUID REFERENCES users(id),           -- internal signatory
  full_name    TEXT NOT NULL,
  email        TEXT NOT NULL,
  sign_order   INT NOT NULL DEFAULT 1,              -- same order number = parallel
  status       signature_status NOT NULL DEFAULT 'pending',
  sign_token   TEXT UNIQUE,                         -- link sent to signer
  signed_at    TIMESTAMPTZ,
  signature_data TEXT                               -- drawn/typed signature
);

CREATE TABLE renewal_alerts (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contract_id UUID NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
  days_before INT NOT NULL CHECK (days_before IN (180,90,60,30)),
  notified_at TIMESTAMPTZ,
  UNIQUE (contract_id, days_before)
);

-- =====================================================================
-- INTEGRATIONS
-- =====================================================================
CREATE TABLE communications (          -- email / SMS / call log linked to CRM records
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  channel     comm_channel NOT NULL,
  direction   TEXT NOT NULL DEFAULT 'outbound',     -- inbound | outbound
  account_id  UUID REFERENCES accounts(id),
  contact_id  UUID REFERENCES contacts(id),
  opportunity_id UUID REFERENCES opportunities(id),
  subject     TEXT,
  body        TEXT,
  user_id     UUID REFERENCES users(id),
  status      TEXT DEFAULT 'sent',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE integration_configs (     -- ERP, eSPF, email, SMS, CTI
  id         SERIAL PRIMARY KEY,
  name       TEXT UNIQUE NOT NULL,     -- 'erp' | 'espf' | 'smtp' | 'sms_gateway' | 'cti'
  base_url   TEXT,
  field_mapping JSONB NOT NULL DEFAULT '{}',
  is_enabled BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE api_keys (                -- system-to-system auth
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name       TEXT NOT NULL,
  key_hash   TEXT NOT NULL,
  is_active  BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sync_logs (
  id          BIGSERIAL PRIMARY KEY,
  integration TEXT NOT NULL,
  direction   TEXT NOT NULL,            -- push | pull
  entity_type TEXT, entity_id TEXT,
  status      TEXT NOT NULL,            -- success | failed
  message     TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =====================================================================
-- Convenience views (dashboard / VSI owners can add more in migrations)
-- =====================================================================
CREATE VIEW v_pipeline_summary AS
SELECT maturity, stage, COUNT(*) AS deals, SUM(amount) AS total_amount, SUM(weighted_amount) AS weighted_amount
FROM opportunities WHERE stage NOT IN ('closed_won','closed_lost')
GROUP BY maturity, stage;

CREATE VIEW v_vertical_revenue AS
SELECT v.id AS vertical_id, v.name AS vertical, COUNT(a.id) AS accounts, COALESCE(SUM(a.contracted_revenue),0) AS revenue
FROM verticals v LEFT JOIN accounts a ON a.vertical_id = v.id AND a.status <> 'churned'
GROUP BY v.id, v.name ORDER BY revenue DESC;

CREATE VIEW v_contracts_expiring AS
SELECT c.*, a.company_name, (c.expiry_date - CURRENT_DATE) AS days_to_expiry
FROM contracts c JOIN accounts a ON a.id = c.account_id
WHERE c.status = 'active' AND c.expiry_date <= CURRENT_DATE + INTERVAL '180 days';
