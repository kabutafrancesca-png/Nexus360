"""Experiential Journey Tracker module.  OWNER: Member 3

TODO (see docs/TASKS.md for the full checklist):
- Log data centre tours, demos, events (+ attendees)
- Trigger: qualifying engagement -> bump opp maturity, create task, notify manager
- Engagement history per account + analytics
- Tasks with SLA + notifications

Conventions:
  - Page routes render templates in app/templates/journey/
  - JSON API routes live under /journey/api/... and return api_ok()/api_error()
  - Protect every route with @login_required or @role_required(...)
  - Call audit(...) on create/update/delete
"""
from flask import Blueprint, render_template, request
from app.db import query_all, query_one, execute
from app.utils import api_ok, api_error, audit
from app.modules.auth.routes import login_required, role_required

bp = Blueprint("journey", __name__)


@bp.route("/")
@login_required
def index():
    return render_template("journey/index.html", title="Experiential Journey Tracker")


@bp.route("/api/ping")
@login_required
def ping():
    return api_ok("journey module is wired up")
