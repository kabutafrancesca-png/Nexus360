# Nexus 360 — Infratel Sales & Customer Platform

A unified CRM and account management system for Infratel's sales team.
Manages customers, pipeline, engagements, contracts, and cross-sell intelligence in one place.

---

## Quick Start (local — no Supabase needed)

```bash
# 1. Clone the repo
git clone https://github.com/kabutafrancesca-png/Nexus360.git
cd Nexus360

# 2. Create and activate virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows PowerShell
# source .venv/bin/activate        # Mac / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up your environment file
copy .env.example .env             # Windows
# cp .env.example .env             # Mac / Linux
# Open .env and fill in SECRET_KEY (see instructions inside)

# 5. Create the local database and seed demo data
python db/init_local.py

# 6. Run the app
python run.py
```

App runs at **http://127.0.0.1:5000**

Demo logins (password for all: `nexus123`):

| Email | Role |
|---|---|
| admin@infratel.test | Admin |
| manager@infratel.test | Sales Manager |
| am@infratel.test | Account Manager |
| rep@infratel.test | Sales Rep |
| exec@infratel.test | Executive |

---

## Project Structure

```
Nexus360/
  app/
    modules/          ← one folder per module (each person owns theirs)
      auth/           ← Person 1
      dashboard/      ← Person 1
      cims/           ← Person 2
      pipeline/       ← Person 3
      journey/        ← Person 3
      vsi/            ← Person 4
      crosssell/      ← Person 4
      contracts/      ← Person 5
      integrations/   ← Person 5
    static/           ← CSS, JS, images
    templates/        ← HTML templates (Jinja2)
    db.py             ← database helper (query_all, query_one, execute)
    utils.py          ← audit(), api_ok(), api_error()
  db/
    schema.sql        ← Postgres/Supabase schema (source of truth)
    schema_sqlite.sql ← SQLite schema (local dev fallback)
    seed.py           ← demo data
    init_local.py     ← one-command local DB setup
  docs/               ← HOW_IT_WORKS.md, TASKS.md, WORKFLOW.md, diagrams
  config.py           ← Flask config (reads from .env)
  run.py              ← entry point
  requirements.txt    ← Python dependencies
  .env.example        ← environment variable template (copy to .env)
```

---

## Database

The app works with **two backends** — no config change needed:

| Situation | What happens |
|---|---|
| `DATABASE_URL` not set in `.env` | Uses `db/nexus360_local.sqlite3` automatically |
| `DATABASE_URL=postgresql://...` in `.env` | Connects to Supabase/Postgres |

To set up the local SQLite database:
```bash
python db/init_local.py
```

To apply the Postgres schema on Supabase:
```
Supabase → SQL Editor → paste db/schema.sql → Run
```

---

## Daily Workflow

```bash
# Every time before you start working
git pull origin main

# Run the app
python run.py

# After making changes — test first, then commit and push
git add app/modules/<your-module>/
git commit -m "module: what you did"
git pull origin main        # pull again before pushing
git push origin main
```

Full workflow guide: [`docs/WORKFLOW.md`](docs/WORKFLOW.md)  
Task assignments: [`docs/ASSIGNMENTS.md`](docs/ASSIGNMENTS.md)  
How the system works: [`docs/HOW_IT_WORKS.md`](docs/HOW_IT_WORKS.md)

---

## Writing Routes

Every route must use `?` as the SQL placeholder (works for both SQLite and Postgres):

```python
from app.db import query_all, query_one, execute
from app.utils import api_ok, audit
from app.modules.auth.routes import login_required, role_required

@bp.route("/api/accounts")
@login_required
def api_accounts():
    rows = query_all("SELECT * FROM accounts WHERE status = ?", ("active",))
    return api_ok(rows)
```

---

## Tech Stack

- **Backend:** Python 3.12, Flask 3.0
- **Database:** PostgreSQL (Supabase) in production, SQLite for local dev
- **Frontend:** Jinja2 templates, vanilla JS, Chart.js
- **Auth:** Session-based with RBAC (role-based access control)
- **Deployment:** Render / Railway (gunicorn)
