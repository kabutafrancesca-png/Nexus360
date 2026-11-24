"""VSI & ABM Engine module.  OWNER: Member 4

TODO (see docs/TASKS.md for the full checklist):
- Revenue ranking by vertical, sector heatmap
- Top account ranking (strategic value score)
- Account map (subsidiaries), white-space analysis
- Buying committee relationship graph (contacts by decision_role)
- Opportunity scoring for ABM

Conventions:
  - Page routes render templates in app/templates/vsi/
  - JSON API routes live under /vsi/api/... and return api_ok()/api_error()
  - Protect every route with @login_required or @role_required(...)
  - Call audit(...) on create/update/delete
"""
from flask import Blueprint, render_template, request
from app.db import query_all, query_one, execute
from app.utils import api_ok, api_error, audit
from app.modules.auth.routes import login_required, role_required

bp = Blueprint("vsi", __name__)


@bp.route("/")
@login_required
def index():
    return render_template("vsi/index.html", title="VSI & ABM Engine")


@bp.route("/api/ping")
@login_required
def ping():
    return api_ok("vsi module is wired up")
