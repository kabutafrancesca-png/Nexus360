"""Executive Dashboard module.  OWNER: Member 7

TODO (see docs/TASKS.md for the full checklist):
- KPI cards (pipeline value, weighted forecast, win rate, renewals due)
- Pipeline funnel + maturity distribution charts (Chart.js)
- Forecast dashboard + forecast variance
- Aggregation endpoints reading from other modules' tables

Conventions:
  - Page routes render templates in app/templates/dashboard/
  - JSON API routes live under /dashboard/api/... and return api_ok()/api_error()
  - Protect every route with @login_required or @role_required(...)
  - Call audit(...) on create/update/delete
"""
from flask import Blueprint, render_template, request
from app.db import query_all, query_one, execute
from app.utils import api_ok, api_error, audit
from app.modules.auth.routes import login_required, role_required

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
def index():
    return render_template("dashboard/index.html", title="Executive Dashboard")


@bp.route("/api/ping")
@login_required
def ping():
    return api_ok("dashboard module is wired up")
