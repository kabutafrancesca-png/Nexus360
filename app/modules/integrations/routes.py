"""Integrations & API module.  OWNER: Member 8

TODO (see docs/TASKS.md for the full checklist):
- Email/SMS/call logging (communications table, provider stubs)
- ERP + eSPF bridge stubs (integration_configs, sync_logs)
- API key auth for system-to-system endpoints
- Swagger/OpenAPI-style docs page

Conventions:
  - Page routes render templates in app/templates/integrations/
  - JSON API routes live under /integrations/api/... and return api_ok()/api_error()
  - Protect every route with @login_required or @role_required(...)
  - Call audit(...) on create/update/delete
"""
from flask import Blueprint, render_template, request
from app.db import query_all, query_one, execute
from app.utils import api_ok, api_error, audit
from app.modules.auth.routes import login_required, role_required

bp = Blueprint("integrations", __name__)


@bp.route("/")
@login_required
def index():
    return render_template("integrations/index.html", title="Integrations & API")


@bp.route("/api/ping")
@login_required
def ping():
    return api_ok("integrations module is wired up")
