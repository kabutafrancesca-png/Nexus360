# Team Assignments — Nexus 360 (5 members)

Work packages from TASKS.md are distributed across 5 people.
Each person owns their module folders end-to-end: routes, templates, any new migrations.
Shared files (`base.html`, `main.css`, `db.py`, `schema.sql`, `config.py`) belong to **Person 1 (Lead)** only.

---

## Person 1 — Lead / Integrator + Dashboard
**Modules:** `auth`, `dashboard` · **WP0 + WP7**
**Starts:** Day 1, first — sets up the foundation everyone else depends on.

### Tasks
- [ ] Create Supabase project, run `db/schema.sql` + `db/seed.py`, share `DATABASE_URL` with the team
- [ ] Set repo branch protection: no direct pushes to `main`, PRs required
- [ ] Review and merge all Pull Requests; keep `main` always runnable
- [ ] Admin user management page (create users, assign roles)
- [ ] Shared layout polish — `base.html`, `main.css`, logo, nav active-state
- [ ] **(DEMO)** Executive KPIs dashboard: pipeline value, weighted forecast, win rate, renewals due, at-risk accounts
- [ ] Charts on dashboard: funnel, maturity distribution, forecast vs actual (Chart.js)
- [ ] CSV / PDF export of dashboard reports
- [ ] Final demo script, pitch deck, and deployment (Render / Railway)

### Files to edit
```
app/modules/auth/
app/modules/dashboard/
app/templates/auth/
app/templates/dashboard/
app/templates/base.html
app/static/css/main.css
db/schema.sql  (owns this)
```

---

## Person 2 — CIMS (Customer Records)
**Module:** `cims` · **WP1**
**Starts:** As soon as Person 1 shares the DATABASE_URL and the skeleton is on `main`.

### Tasks
- [ ] Account create / edit forms with search + filters (vertical, tier, region, status)
- [ ] Contacts CRUD + contact hierarchy (reports-to)
- [ ] **(DEMO)** Single Customer View page: health score, open opportunities, contracts, engagement timeline, services used, status flag
- [ ] Audit log viewer (admin-only page)
- [ ] Role-based field hiding: pricing visible to managers only

### Files to edit
```
app/modules/cims/
app/templates/cims/
db/migrations/  (if new columns needed)
```

---

## Person 3 — Pipeline + Journey Tracker
**Modules:** `pipeline`, `journey` · **WP2 + WP3**
**Starts:** Same time as Person 2, but agree with the team on the `recalculate_maturity` function signature on Day 1 — Person 4's cross-sell also calls it.

### Tasks

#### Pipeline (WP2)
- [ ] Lead CRUD + lead → opportunity conversion
- [ ] **(DEMO)** Kanban pipeline board by stage with drag-and-drop stage change
- [ ] Weighted pipeline + maturity grading (Bronze / Silver / Gold / Platinum)
- [ ] Conversion analytics; dormant-opportunity score degradation
- [ ] Expose `recalculate_maturity(opp_id)` in `app/modules/pipeline/service.py`

#### Journey Tracker (WP3)
- [ ] **(DEMO)** Log a DC tour / demo / event form with attendees
- [ ] **(DEMO)** Trigger on qualifying event: bump maturity (calls `recalculate_maturity`), create follow-up task with SLA, notify sales manager
- [ ] Engagement history per account, attendance analytics
- [ ] Task list + notifications bell

### Files to edit
```
app/modules/pipeline/
app/modules/journey/
app/templates/pipeline/
app/templates/journey/
db/migrations/  (if new columns needed)
```

---

## Person 4 — VSI & ABM + Cross-Sell Engine
**Modules:** `vsi`, `crosssell` · **WP4 + WP5**
**Starts:** After Person 2's account list endpoint is working (needs account + vertical data) and Person 3 has exposed `recalculate_maturity`.

### Tasks

#### VSI & ABM (WP4)
- [ ] **(DEMO)** Revenue ranking by vertical + sector heatmap (using `v_vertical_revenue`)
- [ ] Top account ranking by `strategic_score`
- [ ] Account subsidiary map + white-space view
- [ ] **(DEMO)** Buying committee relationship graph (contacts by `decision_role`)

#### Cross-Sell Engine (WP5)
- [ ] Usage analytics view per account
- [ ] **(DEMO)** Rule engine: rack utilisation > 80% → scale-up, no DR product → recommend DRaaS, etc.
- [ ] Ranked recommendations list (probability × revenue impact) with visible "why" signals
- [ ] Accept / dismiss recommendation; convert recommendation into an opportunity (calls `pipeline/service.py`)

### Files to edit
```
app/modules/vsi/
app/modules/crosssell/
app/templates/vsi/
app/templates/crosssell/
db/migrations/  (if new columns needed)
```

---

## Person 5 — Contracts + Integrations
**Modules:** `contracts`, `integrations` · **WP6 + WP8**
**Starts:** After Person 3 has the pipeline opportunity flow working (contracts need a closed opportunity to exist).

### Tasks

#### Contracts (WP6)
- [ ] Contract generator from template (auto-fill placeholders from account data)
- [ ] PDF export + contract repository with search + PDF upload (Supabase Storage or `uploads/`)
- [ ] **(DEMO)** Renewal dashboard (180 / 90 / 60 / 30 day alerts, using `v_contracts_expiring`)
- [ ] **(DEMO)** E-signature flow: signer link by token, sequential/parallel signing, status tracking

#### Integrations (WP8)
- [ ] Email / SMS / call logging UI + provider stubs
- [ ] ERP + eSPF bridge stubs with field-mapping config and sync log viewer
- [ ] API-key auth decorator for `/api/v1/*` routes
- [ ] Simple API documentation page

### Files to edit
```
app/modules/contracts/
app/modules/integrations/
app/templates/contracts/
app/templates/integrations/
db/migrations/  (if new columns needed)
```

---

## Start order at a glance

```
Day 1 morning
└── Person 1: set up Supabase, run schema + seed, share DB URL, push skeleton

Day 1 (once DB URL is shared)
├── Person 2: CIMS — accounts and contacts
├── Person 3: Pipeline — leads, kanban, maturity service
│             Journey — tour logging and trigger (needs service.py first)
└── Person 4: VSI/ABM + Cross-Sell (needs accounts from Person 2 and service.py from Person 3)

After Pipeline opportunities exist
└── Person 5: Contracts (needs closed opps) + Integrations (independent)

All phases
└── Person 1: reviews PRs, merges, keeps main green, builds dashboard as data becomes available
```

## Dependency map

```
Person 1 (skeleton + DB)
    └──> Person 2 (CIMS accounts)
    └──> Person 3 (Pipeline service.py)
              └──> Person 3 (Journey trigger calls service.py)
              └──> Person 4 (Cross-Sell calls service.py to create opp)
              └──> Person 5 (Contracts needs closed opportunities)
    └──> Person 4 (VSI needs accounts from Person 2)
    └──> Person 1 (Dashboard reads all tables — build last)
```

## Key agreement needed on Day 1

| Contract | Owner | Caller |
|---|---|---|
| `pipeline.service.recalculate_maturity(opp_id)` | Person 3 | Person 3 (Journey), Person 4 (Cross-Sell) |
| Account list API `/cims/api/accounts` | Person 2 | Person 4 (VSI heatmap), Person 1 (Dashboard) |
| Opportunity won → creates contract record | Person 3 | Person 5 (Contracts) |

---
*Branch naming: `feature/<module>-<what>` e.g. `feature/pipeline-kanban`, `feature/contracts-esign`*
