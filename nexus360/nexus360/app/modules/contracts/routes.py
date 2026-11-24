"""Contract Management module.  OWNER: Member 6

TODO (see docs/TASKS.md for the full checklist):
- Template-based contract generation (HTML -> PDF)
- Repository + upload/storage of PDFs + search
- Versioning, renewal tracking (180/90/60/30 days)
- E-signature workflow (sequential/parallel signatories, status)

Conventions:
  - Page routes render templates in app/templates/contracts/
  - JSON API routes live under /contracts/api/... and return api_ok()/api_error()
  - Protect every route with @login_required or @role_required(...)
  - Call audit(...) on create/update/delete
"""
from flask import Blueprint, render_template, request
from app.db import query_all, query_one, execute
from app.utils import api_ok, api_error, audit
from app.modules.auth.routes import login_required, role_required

bp = Blueprint("contracts", __name__)


@bp.route("/")
@login_required
def index():
    return render_template("contracts/index.html", title="Contract Management")


@bp.route("/api/ping")
@login_required
def ping():
    return api_ok("contracts module is wired up")
