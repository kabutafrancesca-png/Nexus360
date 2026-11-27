"""CIMS - Customer Information Management System.  OWNER: Member 1

REFERENCE IMPLEMENTATION: accounts list + create + detail are working examples.
Copy this pattern in your own module.

TODO:
- Account edit/delete + status flags (active, at_risk, renewal_due, expansion_ready, churned)
- Contacts CRUD + contact hierarchy (reports_to_id)
- Single Customer View page (opps, contracts, engagement timeline, health score)
- Search + filters (vertical, tier, region, status)
- Audit log viewer (admin only), data classification tags
"""
from flask import Blueprint, render_template, request, redirect, url_for
from app.db import query_all, query_one, execute
from app.utils import api_ok, api_error, audit
from app.modules.auth.routes import login_required, role_required

bp = Blueprint("cims", __name__)


@bp.route("/")
@login_required
def index():
    accounts = query_all(
        """SELECT a.id, a.company_name, a.tier, a.region, a.status, a.health_score, v.name AS vertical
           FROM accounts a LEFT JOIN verticals v ON v.id = a.vertical_id
           ORDER BY a.company_name"""
    )
    return render_template("cims/index.html", title="Customers (CIMS)", accounts=accounts)


@bp.route("/accounts/<uuid:account_id>")
@login_required
def account_detail(account_id):
    account = query_one("SELECT * FROM accounts WHERE id = ?", (str(account_id),))
    contacts = query_all("SELECT * FROM contacts WHERE account_id = ?", (str(account_id),))
    audit("view", "account", str(account_id))
    return render_template("cims/account_detail.html", title="Account", account=account, contacts=contacts)


@bp.route("/api/accounts", methods=["GET"])
@login_required
def api_accounts():
    return api_ok(query_all("SELECT id, company_name, tier, status FROM accounts ORDER BY company_name"))


@bp.route("/api/accounts", methods=["POST"])
@role_required("account_manager", "sales_manager")
def api_create_account():
    data = request.get_json() or {}
    if not data.get("company_name"):
        return api_error("company_name is required")
    row = execute(
        """INSERT INTO accounts (company_name, vertical_id, tier, region)
           VALUES (?, ?, ?, ?) RETURNING *""",
        (data["company_name"], data.get("vertical_id"), data.get("tier", "standard"), data.get("region")),
    )
    audit("create", "account", str(row["id"]), data)
    return api_ok(row), 201
