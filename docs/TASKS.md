# Nexus 360 - Work Packages
Branch name: `feature/<module>-<task>`. Each person owns one module folder.
Proposal "must show in demo" items are marked **(DEMO)**.

## WP0 - Lead / Integrator (Member 0)
- [ ] Supabase project, run schema.sql + seed.py, share DATABASE_URL
- [ ] Repo protection, PR reviews, merge, keep `main` always runnable
- [ ] Auth/RBAC (done in skeleton), admin user management page, shared layout polish
- [ ] Final demo script + pitch deck + deployment (Render/Railway)

## WP1 - CIMS (Member 1)  `app/modules/cims`
Tables: accounts, contacts, account_services, audit_logs
- [ ] Account create/edit forms, search + filters (vertical, tier, region, status)
- [ ] Contacts CRUD + hierarchy
- [ ] **(DEMO)** Single Customer View: health score, opps, contracts, timeline, services, status flag
- [ ] Audit log viewer (admin), role-based field hiding (pricing visible to managers only)

## WP2 - CRM & Pipeline (Member 2)  `app/modules/pipeline`
Tables: leads, opportunities, opportunity_history
- [ ] Lead CRUD, lead -> opportunity conversion (lead vs pipeline separation)
- [ ] **(DEMO)** Kanban pipeline board by stage, drag/drop stage change
- [ ] Weighted pipeline + maturity grading Bronze/Silver/Gold/Platinum (see proposal table)
- [ ] Conversion analytics; dormant-opportunity score degradation function
- [ ] Expose `recalculate_maturity(opp_id)` in `pipeline/service.py` (Member 3 calls it)

## WP3 - Experiential Journey Tracker (Member 3)  `app/modules/journey`
Tables: engagement_events, engagement_attendees, tasks, notifications
- [ ] **(DEMO)** Log DC tour / demo / event form with attendees
- [ ] **(DEMO)** Trigger: qualifying event -> bump maturity, create follow-up task with SLA, notify sales manager
- [ ] Engagement history per account, attendance analytics, task list + notifications bell

## WP4 - VSI & ABM (Member 4)  `app/modules/vsi`
Tables: verticals, accounts, contacts, sector_snapshots, white_space
- [ ] **(DEMO)** Revenue ranking by vertical + sector heatmap (use `v_vertical_revenue`)
- [ ] Top account ranking (strategic_score formula)
- [ ] Account map (subsidiaries) + white space
- [ ] **(DEMO)** Buying committee relationship graph (contacts by decision_role)

## WP5 - Cross-Sell Engine (Member 5)  `app/modules/crosssell`
Tables: usage_metrics, recommendations, account_services, products
- [ ] Usage analytics view per account
- [ ] **(DEMO)** Rule engine from proposal table (rack util >80% -> scale-up, no DR -> DRaaS ...)
- [ ] Ranked recommendations (probability x revenue impact) with visible "why" signals
- [ ] Accept/dismiss, convert recommendation into an opportunity (call pipeline service)

## WP6 - Contracts (Member 6)  `app/modules/contracts`
Tables: contract_templates, contracts, contract_versions, contract_signatories, renewal_alerts
- [ ] Contract generator from template (placeholders filled from account), PDF export
- [ ] Repository with search + PDF upload (Supabase Storage or `uploads/`)
- [ ] **(DEMO)** Renewal dashboard (180/90/60/30 days, use `v_contracts_expiring`)
- [ ] **(DEMO)** E-signature flow: signer link by token, sequential/parallel, status tracking

## WP7 - Dashboard & Reporting (Member 7)  `app/modules/dashboard`
- [ ] **(DEMO)** Executive KPIs: pipeline value, weighted forecast, win rate, renewals due, at-risk accounts
- [ ] Charts: funnel, maturity distribution, forecast vs actual (Chart.js)
- [ ] CSV/PDF export of reports

## WP8 - Integrations & API (Member 8)  `app/modules/integrations`
Tables: communications, integration_configs, api_keys, sync_logs
- [ ] Email/SMS/call logging UI + provider stubs
- [ ] ERP + eSPF bridge stubs with field mapping config and sync log
- [ ] API-key auth decorator for `/api/v1/*`, simple API docs page

## Merge order / integration points
1. Lead merges skeleton -> everyone branches.
2. Pipeline (WP2) `service.py` and Journey (WP3) trigger are the key dependency; agree on function signature on day 1.
3. Dashboard (WP7) reads other modules' tables only (no importing their code).
