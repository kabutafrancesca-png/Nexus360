"""Executive Dashboard.  OWNER: Person 1 (Lead).

KPI cards, pipeline funnel, maturity distribution, renewals due, at-risk accounts.
All data is read-only — this module never writes to the DB.
"""
from flask import Blueprint, render_template
from app.db import query_all, query_one
from app.utils import api_ok, audit
from app.modules.auth.routes import login_required, role_required

bp = Blueprint("dashboard", __name__)


# ── Page ──────────────────────────────────────────────────────────────────────

@bp.route("/")
@login_required
def index():
    kpis        = _kpis()
    maturity    = _maturity_dist()
    renewals    = _renewals_due()
    at_risk     = _at_risk()
    audit("view", "dashboard")
    return render_template("dashboard/index.html",
                           title="Executive Dashboard",
                           kpis=kpis,
                           maturity=maturity,
                           renewals=renewals,
                           at_risk=at_risk)


# ── API endpoints (Chart.js calls these) ──────────────────────────────────────

@bp.route("/api/kpis")
@login_required
def api_kpis():
    return api_ok(_kpis())


@bp.route("/api/pipeline-funnel")
@login_required
def api_pipeline_funnel():
    rows = query_all("""
        SELECT stage, COUNT(*) AS deals, SUM(amount) AS total
        FROM   opportunities
        WHERE  stage NOT IN ('closed_won','closed_lost')
        GROUP  BY stage
        ORDER  BY total DESC
    """)
    return api_ok(rows)


@bp.route("/api/maturity-dist")
@login_required
def api_maturity_dist():
    return api_ok(_maturity_dist())


# ── Private helpers ───────────────────────────────────────────────────────────

def _kpis():
    pipeline = query_one("""
        SELECT
            COUNT(*)                       AS open_deals,
            COALESCE(SUM(amount), 0)       AS pipeline_value,
            COALESCE(SUM(weighted_amount), 0) AS weighted_forecast
        FROM opportunities
        WHERE stage NOT IN ('closed_won','closed_lost')
    """) or {}

    win_rate = query_one("""
        SELECT
            CASE WHEN COUNT(*) = 0 THEN 0
                 ELSE ROUND(
                     100.0 * SUM(CASE WHEN stage='closed_won' THEN 1 ELSE 0 END) / COUNT(*), 1
                 )
            END AS win_rate
        FROM opportunities
        WHERE stage IN ('closed_won','closed_lost')
    """) or {}

    renewals = query_one("""
        SELECT COUNT(*) AS renewals_due
        FROM   v_contracts_expiring
        WHERE  days_to_expiry BETWEEN 0 AND 90
    """) or {}

    at_risk = query_one("""
        SELECT COUNT(*) AS at_risk
        FROM   accounts
        WHERE  status IN ('at_risk','renewal_due')
    """) or {}

    return {
        "open_deals":        pipeline.get("open_deals", 0),
        "pipeline_value":    pipeline.get("pipeline_value", 0),
        "weighted_forecast": pipeline.get("weighted_forecast", 0),
        "win_rate":          win_rate.get("win_rate", 0),
        "renewals_due":      renewals.get("renewals_due", 0),
        "at_risk_accounts":  at_risk.get("at_risk", 0),
    }


def _maturity_dist():
    return query_all("""
        SELECT maturity, COUNT(*) AS deals, COALESCE(SUM(amount),0) AS total
        FROM   opportunities
        WHERE  stage NOT IN ('closed_won','closed_lost')
        GROUP  BY maturity
        ORDER  BY CASE maturity
            WHEN 'bronze'   THEN 1
            WHEN 'silver'   THEN 2
            WHEN 'gold'     THEN 3
            WHEN 'platinum' THEN 4
        END
    """)


def _renewals_due():
    return query_all("""
        SELECT contract_number, title, company_name,
               expiry_date, annual_value,
               days_to_expiry AS days_left
        FROM   v_contracts_expiring
        WHERE  days_to_expiry BETWEEN 0 AND 90
        ORDER  BY expiry_date
    """)


def _at_risk():
    return query_all("""
        SELECT a.company_name, a.status, a.health_score,
               a.region, v.name AS vertical
        FROM   accounts  a
        LEFT JOIN verticals v ON v.id = a.vertical_id
        WHERE  a.status IN ('at_risk','renewal_due')
        ORDER  BY a.health_score
        LIMIT  10
    """)
