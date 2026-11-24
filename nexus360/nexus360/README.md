# Infratel Nexus 360
B2B Commercial Intelligence Platform - INFRATEL-UNZA iHub Hackathon 2026, Challenge 2.

**Stack:** Flask (Python) | Jinja templates + HTML/CSS/JS | PostgreSQL (Supabase or local)

## Start here
- **New to the project?** Read [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) (plain-English walkthrough of the whole system)
- **What do I build?** [docs/TASKS.md](docs/TASKS.md)
- **How do we use Git together?** [docs/WORKFLOW.md](docs/WORKFLOW.md)

## 1. Setup (everyone, ~5 minutes)
```bash
git clone <repo-url> && cd nexus360
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # Windows: copy .env.example .env  -> then fill DATABASE_URL
python run.py                     # http://localhost:5000
```
Database: the team shares ONE Supabase project (ask the lead for the `DATABASE_URL`). Use the **Session pooler** connection string.
Lead runs once: paste `db/schema.sql` into the Supabase SQL Editor, then `python db/seed.py`.

Demo login: `admin@infratel.test` / `nexus123`

## 2. Project layout
```
app/
  __init__.py          app factory, registers every module blueprint
  db.py                query_all / query_one / execute helpers
  utils.py             audit(), api_ok(), api_error()
  modules/<name>/routes.py     <- YOU WORK HERE (one folder per module)
  templates/<name>/            <- your pages
  static/css, static/js        shared assets (put module JS in static/js/<name>.js)
db/schema.sql          source of truth for the DB
db/migrations/         schema changes after day 1 (001_xxx.sql ...)
docs/TASKS.md          who builds what
```
`app/modules/cims/` is a fully working reference (list, detail, JSON API, audit). Copy its pattern.

## 3. Git rules (so we don't collide)
- `main` is protected: nobody pushes directly. Work on `feature/<module>-<what>`, open a PR, lead merges.
- **Only edit files inside your own module folder + your own templates folder.** Need a change elsewhere? Ask the owner or open a PR comment.
- Shared files (`base.html`, `main.css`, `db.py`, `schema.sql`) are lead-owned. Need a new column/table? Add `db/migrations/NNN_description.sql` and tell the lead.
- Pull from `main` daily: `git pull origin main --rebase`.
- Never commit `.env`.

## 4. Conventions
- Page routes: `render_template("<module>/page.html", ...)`. Extend `base.html`.
- JSON routes: `/<module>/api/...`, return `api_ok(data)` / `api_error("msg")`.
- Always parameterise SQL (`%s`), never f-strings with user input.
- Protect routes with `@login_required` / `@role_required("sales_manager")`. Log changes with `audit(...)`.
- Frontend: call APIs with `api()` from `static/js/api.js`. Charts: Chart.js via CDN.
