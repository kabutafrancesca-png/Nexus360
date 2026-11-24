"""CRM & Pipeline module.  OWNER: Member 2

TODO (see docs/TASKS.md for the full checklist):
- Lead management (CRUD, source, status)
- Lead vs pipeline separation: convert lead -> opportunity
- Opportunity tracking, stages, kanban board
- Weighted pipeline + maturity grading (Bronze/Silver/Gold/Platinum)
- Conversion analytics + score degradation for dormant opps

Conventions:
  - Page routes render templates in app/templates/pipeline/
  - JSON API routes live under /pipeline/api/... and return api_ok()/api_error()
  - Protect every route with @login_required or @role_required(...)
  - Call audit(...) on create/update/delete
"""
from flask import Blueprint, render_template, request
from app.db import query_all, query_one, execute
from app.utils import api_ok, api_error, audit
from app.modules.auth.routes import login_required, role_required

bp = Blueprint("pipeline", __name__)


@bp.route("/")
@login_required
def index():
    return render_template("pipeline/index.html", title="CRM & Pipeline")


@bp.route("/api/ping")
@login_required
def ping():
    return api_ok("pipeline module is wired up")
