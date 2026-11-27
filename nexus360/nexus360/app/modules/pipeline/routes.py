"""CRM & Pipeline module.  OWNER: Member 2 (Person 3)

Implements:
- Lead CRUD and Lead -> Account + Opportunity conversion
- Kanban pipeline board with stage transitions & history logging
- Weighted pipeline + maturity grading (Bronze / Silver / Gold / Platinum)
- Conversion analytics & dormant-opportunity score degradation
"""
import uuid
from datetime import datetime, timezone

from flask import Blueprint, render_template, request, session

from app.db import execute, query_all, query_one
from app.modules.auth.routes import login_required, role_required
from app.modules.pipeline import service
from app.utils import api_error, api_ok, audit

bp = Blueprint("pipeline", __name__)


def _enrich_opportunity(opp: dict) -> dict:
    row = service.serialize_row(opp)
    days = service.compute_days_inactive(row.get("last_activity_at"))
    is_open = row.get("stage") not in ("closed_won", "closed_lost")
    row["days_since_activity"] = days
    row["is_dormant"] = bool(is_open and days >= service.DEFAULT_DORMANT_DAYS)
    return row


@bp.route("/")
@login_required
def index():
    return render_template("pipeline/index.html", title="CRM & Pipeline")


@bp.route("/api/ping")
@login_required
def ping():
    return api_ok("pipeline module is wired up")


@bp.route("/api/meta", methods=["GET"])
@login_required
def api_meta():
    accounts = service.serialize_rows(
        query_all("SELECT id, company_name, tier, status, owner_id FROM accounts ORDER BY company_name")
    )
    verticals = service.serialize_rows(query_all("SELECT id, name FROM verticals ORDER BY name"))
    products = service.serialize_rows(query_all("SELECT id, name, category FROM products ORDER BY name"))
    users = service.serialize_rows(
        query_all(
            "SELECT id, full_name, email, role FROM users WHERE is_active = ? ORDER BY full_name",
            (True,),
        )
    )
    return api_ok(
        {
            "accounts": accounts,
            "verticals": verticals,
            "products": products,
            "users": users,
            "stages": list(service.OPP_STAGES),
            "active_stages": list(service.ACTIVE_STAGES),
            "maturities": list(service.MATURITY_TIERS),
            "lead_statuses": list(service.LEAD_STATUSES),
            "lead_sources": list(service.LEAD_SOURCES),
            "dormant_days": service.DEFAULT_DORMANT_DAYS,
            "current_user": {
                "id": session.get("user_id"),
                "role": session.get("role"),
                "full_name": session.get("full_name"),
            },
        }
    )


# ---------------------------------------------------------------------------
# Leads CRUD & Conversion
# ---------------------------------------------------------------------------

@bp.route("/api/leads", methods=["GET"])
@login_required
def api_list_leads():
    status = request.args.get("status", "").strip()
    source = request.args.get("source", "").strip()
    q = request.args.get("q", "").strip()

    if status and status not in service.LEAD_STATUSES:
        return api_error(f"Invalid lead status: {status}")

    clauses = []
    params = []
    if status:
        clauses.append("l.status = ?")
        params.append(status)
    if source:
        clauses.append("l.source = ?")
        params.append(source)
    if q:
        clauses.append("(LOWER(l.company_name) LIKE LOWER(?) OR LOWER(COALESCE(l.contact_name, '')) LIKE LOWER(?) OR LOWER(COALESCE(l.contact_email, '')) LIKE LOWER(?))")
        like = f"%{q}%"
        params.extend([like, like, like])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = query_all(
        f"""SELECT l.*, v.name AS vertical_name, u.full_name AS owner_name,
                   a.company_name AS converted_account_name
            FROM leads l
            LEFT JOIN verticals v ON v.id = l.vertical_id
            LEFT JOIN users u ON u.id = l.owner_id
            LEFT JOIN accounts a ON a.id = l.converted_account_id
            {where}
            ORDER BY l.created_at DESC""",
        tuple(params),
    )
    return api_ok(service.serialize_rows(rows))


@bp.route("/api/leads", methods=["POST"])
@login_required
def api_create_lead():
    data = request.get_json() or {}
    company_name = (data.get("company_name") or "").strip()
    if not company_name:
        return api_error("company_name is required")

    status = (data.get("status") or "new").strip()
    if status not in service.LEAD_STATUSES:
        return api_error(f"Invalid lead status: {status}")

    try:
        score = int(data.get("score") or 0)
    except (TypeError, ValueError):
        return api_error("score must be an integer")
    score = max(0, min(100, score))

    lead_id = str(uuid.uuid4())
    owner_id = data.get("owner_id") or session.get("user_id")
    vertical_id = int(data["vertical_id"]) if data.get("vertical_id") else None

    execute(
        """INSERT INTO leads
             (id, company_name, contact_name, contact_email, contact_phone,
              vertical_id, source, status, score, owner_id, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            lead_id,
            company_name,
            (data.get("contact_name") or "").strip() or None,
            (data.get("contact_email") or "").strip() or None,
            (data.get("contact_phone") or "").strip() or None,
            vertical_id,
            (data.get("source") or "website").strip() or None,
            status,
            score,
            owner_id,
            (data.get("notes") or "").strip() or None,
        ),
    )

    row = query_one(
        """SELECT l.*, v.name AS vertical_name, u.full_name AS owner_name
           FROM leads l
           LEFT JOIN verticals v ON v.id = l.vertical_id
           LEFT JOIN users u ON u.id = l.owner_id
           WHERE l.id = ?""",
        (lead_id,),
    )
    audit("create", "lead", lead_id, {"company_name": company_name, "status": status})
    return api_ok(service.serialize_row(row)), 201


@bp.route("/api/leads/<uuid:lead_id>", methods=["PUT"])
@login_required
def api_update_lead(lead_id):
    lid = str(lead_id)
    existing = query_one("SELECT * FROM leads WHERE id = ?", (lid,))
    if not existing:
        return api_error("Lead not found", 404)

    data = request.get_json() or {}
    company_name = (data.get("company_name") if "company_name" in data else existing["company_name"] or "").strip()
    if not company_name:
        return api_error("company_name is required")

    status = (data.get("status") if "status" in data else existing["status"]).strip()
    if status not in service.LEAD_STATUSES:
        return api_error(f"Invalid lead status: {status}")

    try:
        score = int(data["score"]) if "score" in data and data["score"] is not None else int(existing.get("score") or 0)
    except (TypeError, ValueError):
        return api_error("score must be an integer")
    score = max(0, min(100, score))

    vertical_id = (
        int(data["vertical_id"]) if data.get("vertical_id") else None
        if "vertical_id" in data
        else existing.get("vertical_id")
    )

    execute(
        """UPDATE leads
           SET company_name = ?, contact_name = ?, contact_email = ?, contact_phone = ?,
               vertical_id = ?, source = ?, status = ?, score = ?, owner_id = ?, notes = ?,
               updated_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (
            company_name,
            data.get("contact_name", existing.get("contact_name")),
            data.get("contact_email", existing.get("contact_email")),
            data.get("contact_phone", existing.get("contact_phone")),
            vertical_id,
            data.get("source", existing.get("source")),
            status,
            score,
            data.get("owner_id", existing.get("owner_id")),
            data.get("notes", existing.get("notes")),
            lid,
        ),
    )

    updated = query_one(
        """SELECT l.*, v.name AS vertical_name, u.full_name AS owner_name,
                  a.company_name AS converted_account_name
           FROM leads l
           LEFT JOIN verticals v ON v.id = l.vertical_id
           LEFT JOIN users u ON u.id = l.owner_id
           LEFT JOIN accounts a ON a.id = l.converted_account_id
           WHERE l.id = ?""",
        (lid,),
    )
    audit("update", "lead", lid, {"status": [existing["status"], status]})
    return api_ok(service.serialize_row(updated))


@bp.route("/api/leads/<uuid:lead_id>", methods=["DELETE"])
@role_required("account_manager", "sales_manager")
def api_delete_lead(lead_id):
    lid = str(lead_id)
    existing = query_one("SELECT id, company_name FROM leads WHERE id = ?", (lid,))
    if not existing:
        return api_error("Lead not found", 404)

    execute("DELETE FROM leads WHERE id = ?", (lid,))
    audit("delete", "lead", lid, {"company_name": existing["company_name"]})
    return api_ok({"deleted": lid})


@bp.route("/api/leads/<uuid:lead_id>/convert", methods=["POST"])
@login_required
def api_convert_lead(lead_id):
    lid = str(lead_id)
    lead = query_one("SELECT * FROM leads WHERE id = ?", (lid,))
    if not lead:
        return api_error("Lead not found", 404)
    if lead["status"] == "converted":
        return api_error("Lead is already converted")

    data = request.get_json() or {}
    existing_account_id = (data.get("existing_account_id") or "").strip() or None
    opp_name = (data.get("opportunity_name") or f"{lead['company_name']} - New Opportunity").strip()
    stage = (data.get("stage") or "qualification").strip()
    if stage not in service.OPP_STAGES:
        return api_error(f"Invalid stage: {stage}")

    try:
        amount = float(data.get("amount") or 0)
    except (TypeError, ValueError):
        return api_error("amount must be numeric")
    if amount < 0:
        return api_error("amount cannot be negative")

    owner_id = data.get("owner_id") or lead.get("owner_id") or session.get("user_id")
    created_account = False

    if existing_account_id:
        acc = query_one("SELECT * FROM accounts WHERE id = ?", (existing_account_id,))
        if not acc:
            return api_error("Selected existing account was not found", 404)
        account_id = str(acc["id"])
    else:
        account_id = str(uuid.uuid4())
        execute(
            """INSERT INTO accounts
                 (id, company_name, vertical_id, tier, region, status, owner_id)
               VALUES (?, ?, ?, ?, ?, 'active', ?)""",
            (
                account_id,
                lead["company_name"],
                lead.get("vertical_id"),
                (data.get("tier") or "standard").strip(),
                (data.get("region") or "Lusaka").strip(),
                owner_id,
            ),
        )
        created_account = True

        if lead.get("contact_name"):
            contact_id = str(uuid.uuid4())
            execute(
                """INSERT INTO contacts
                     (id, account_id, full_name, email, phone, decision_role)
                   VALUES (?, ?, ?, ?, ?, 'champion')""",
                (
                    contact_id,
                    account_id,
                    lead["contact_name"],
                    lead.get("contact_email"),
                    lead.get("contact_phone"),
                ),
            )
        acc = query_one("SELECT * FROM accounts WHERE id = ?", (account_id,))

    opp = service.create_opportunity(
        account_id=account_id,
        name=opp_name,
        amount=amount,
        stage=stage,
        product_id=data.get("product_id"),
        lead_id=lid,
        expected_close=data.get("expected_close"),
        owner_id=owner_id,
        reason="converted from lead",
        changed_by=session.get("user_id"),
    )

    execute(
        """UPDATE leads
           SET status = 'converted', converted_account_id = ?, updated_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (account_id, lid),
    )

    audit(
        "convert",
        "lead",
        lid,
        {
            "account_id": account_id,
            "created_account": created_account,
            "opportunity_id": opp["id"],
        },
    )
    return api_ok(
        {
            "lead_id": lid,
            "created_account": created_account,
            "account": service.serialize_row(acc),
            "opportunity": opp,
        }
    ), 201


# ---------------------------------------------------------------------------
# Opportunities & Kanban
# ---------------------------------------------------------------------------

@bp.route("/api/opportunities", methods=["GET"])
@login_required
def api_list_opportunities():
    stage = request.args.get("stage", "").strip()
    maturity = request.args.get("maturity", "").strip()
    account_id = request.args.get("account_id", "").strip()
    owner_id = request.args.get("owner_id", "").strip()
    q = request.args.get("q", "").strip()

    if stage and stage not in service.OPP_STAGES:
        return api_error(f"Invalid stage: {stage}")
    if maturity and maturity not in service.MATURITY_TIERS:
        return api_error(f"Invalid maturity: {maturity}")

    clauses = []
    params = []
    if stage:
        clauses.append("o.stage = ?")
        params.append(stage)
    if maturity:
        clauses.append("o.maturity = ?")
        params.append(maturity)
    if account_id:
        clauses.append("o.account_id = ?")
        params.append(account_id)
    if owner_id:
        clauses.append("o.owner_id = ?")
        params.append(owner_id)
    if q:
        clauses.append("(LOWER(o.name) LIKE LOWER(?) OR LOWER(a.company_name) LIKE LOWER(?))")
        like = f"%{q}%"
        params.extend([like, like])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = query_all(
        f"""SELECT o.*, a.company_name, a.tier AS account_tier,
                   p.name AS product_name, u.full_name AS owner_name
            FROM opportunities o
            JOIN accounts a ON a.id = o.account_id
            LEFT JOIN products p ON p.id = o.product_id
            LEFT JOIN users u ON u.id = o.owner_id
            {where}
            ORDER BY o.updated_at DESC, o.created_at DESC""",
        tuple(params),
    )
    return api_ok([_enrich_opportunity(r) for r in rows])


@bp.route("/api/opportunities", methods=["POST"])
@login_required
def api_create_opportunity():
    data = request.get_json() or {}
    account_id = (data.get("account_id") or "").strip()
    name = (data.get("name") or "").strip()
    stage = (data.get("stage") or "qualification").strip()

    if not account_id:
        return api_error("account_id is required")
    if not name:
        return api_error("name is required")
    if stage not in service.OPP_STAGES:
        return api_error(f"Invalid stage: {stage}")

    acc = query_one("SELECT id FROM accounts WHERE id = ?", (account_id,))
    if not acc:
        return api_error("Account not found", 404)

    try:
        amount = float(data.get("amount") or 0)
    except (TypeError, ValueError):
        return api_error("amount must be numeric")
    if amount < 0:
        return api_error("amount cannot be negative")

    opp = service.create_opportunity(
        account_id=account_id,
        name=name,
        amount=amount,
        stage=stage,
        product_id=data.get("product_id"),
        lead_id=data.get("lead_id"),
        expected_close=data.get("expected_close"),
        owner_id=data.get("owner_id") or session.get("user_id"),
        reason="created manually",
        changed_by=session.get("user_id"),
    )
    audit("create", "opportunity", opp["id"], {"name": name, "stage": stage, "amount": amount})

    enriched = query_one(
        """SELECT o.*, a.company_name, p.name AS product_name, u.full_name AS owner_name
           FROM opportunities o
           JOIN accounts a ON a.id = o.account_id
           LEFT JOIN products p ON p.id = o.product_id
           LEFT JOIN users u ON u.id = o.owner_id
           WHERE o.id = ?""",
        (opp["id"],),
    )
    return api_ok(_enrich_opportunity(enriched)), 201


@bp.route("/api/opportunities/<uuid:opp_id>", methods=["GET"])
@login_required
def api_get_opportunity(opp_id):
    oid = str(opp_id)
    opp = query_one(
        """SELECT o.*, a.company_name, a.tier AS account_tier, a.region AS account_region,
                  p.name AS product_name, u.full_name AS owner_name
           FROM opportunities o
           JOIN accounts a ON a.id = o.account_id
           LEFT JOIN products p ON p.id = o.product_id
           LEFT JOIN users u ON u.id = o.owner_id
           WHERE o.id = ?""",
        (oid,),
    )
    if not opp:
        return api_error("Opportunity not found", 404)

    history = service.serialize_rows(
        query_all(
            """SELECT h.*, u.full_name AS changed_by_name
               FROM opportunity_history h
               LEFT JOIN users u ON u.id = h.changed_by
               WHERE h.opportunity_id = ?
               ORDER BY h.changed_at DESC, h.id DESC""",
            (oid,),
        )
    )
    engagements = service.serialize_rows(
        query_all(
            """SELECT e.*, u.full_name AS facilitator_name
               FROM engagement_events e
               LEFT JOIN users u ON u.id = e.facilitator_id
               WHERE e.opportunity_id = ?
               ORDER BY e.event_date DESC""",
            (oid,),
        )
    )

    payload = _enrich_opportunity(opp)
    payload["history"] = history
    payload["engagements"] = engagements
    return api_ok(payload)


@bp.route("/api/opportunities/<uuid:opp_id>", methods=["PUT"])
@login_required
def api_update_opportunity(opp_id):
    oid = str(opp_id)
    existing = query_one("SELECT * FROM opportunities WHERE id = ?", (oid,))
    if not existing:
        return api_error("Opportunity not found", 404)

    data = request.get_json() or {}
    name = (data.get("name") if "name" in data else existing["name"] or "").strip()
    if not name:
        return api_error("name is required")

    account_id = str(data.get("account_id") or existing["account_id"])
    acc = query_one("SELECT id FROM accounts WHERE id = ?", (account_id,))
    if not acc:
        return api_error("Account not found", 404)

    try:
        amount = float(data["amount"]) if "amount" in data and data["amount"] is not None else float(existing["amount"] or 0)
    except (TypeError, ValueError):
        return api_error("amount must be numeric")
    if amount < 0:
        return api_error("amount cannot be negative")

    product_id = (
        int(data["product_id"]) if data.get("product_id") else None
        if "product_id" in data
        else existing.get("product_id")
    )
    expected_close = (
        (data.get("expected_close") or None)
        if "expected_close" in data
        else existing.get("expected_close")
    )
    owner_id = data.get("owner_id", existing.get("owner_id"))
    lost_reason = data.get("lost_reason", existing.get("lost_reason"))

    sets = [
        "name = ?",
        "account_id = ?",
        "product_id = ?",
        "amount = ?",
        "expected_close = ?",
        "owner_id = ?",
        "lost_reason = ?",
        "last_activity_at = CURRENT_TIMESTAMP",
        "updated_at = CURRENT_TIMESTAMP",
    ]
    win_prob = float(existing.get("win_probability") or 10)
    params = [name, account_id, product_id, amount, expected_close, owner_id, lost_reason]
    if service._is_sqlite():
        sets.append("weighted_amount = ?")
        params.append(round(amount * win_prob / 100.0, 2))
    params.append(oid)

    execute(f"UPDATE opportunities SET {', '.join(sets)} WHERE id = ?", tuple(params))

    service.recalculate_maturity(
        oid,
        reason="opportunity updated",
        changed_by=session.get("user_id"),
        touch_activity=True,
    )
    audit("update", "opportunity", oid, {"name": name, "amount": amount})

    updated = query_one(
        """SELECT o.*, a.company_name, p.name AS product_name, u.full_name AS owner_name
           FROM opportunities o
           JOIN accounts a ON a.id = o.account_id
           LEFT JOIN products p ON p.id = o.product_id
           LEFT JOIN users u ON u.id = o.owner_id
           WHERE o.id = ?""",
        (oid,),
    )
    return api_ok(_enrich_opportunity(updated))


@bp.route("/api/opportunities/<uuid:opp_id>/stage", methods=["PATCH"])
@login_required
def api_move_stage(opp_id):
    oid = str(opp_id)
    data = request.get_json() or {}
    new_stage = (data.get("stage") or "").strip()
    if new_stage not in service.OPP_STAGES:
        return api_error(f"Invalid stage: {new_stage}")

    updated = service.update_opportunity_stage(
        oid,
        new_stage,
        changed_by=session.get("user_id"),
        lost_reason=(data.get("lost_reason") or "").strip() or None,
        reason=(data.get("reason") or "kanban move").strip(),
    )
    if not updated:
        return api_error("Opportunity not found", 404)

    audit(
        "stage_change",
        "opportunity",
        oid,
        {
            "stage": [updated.get("previous_stage"), new_stage],
            "maturity": [updated.get("previous_maturity"), updated.get("maturity")],
        },
    )

    enriched = query_one(
        """SELECT o.*, a.company_name, p.name AS product_name, u.full_name AS owner_name
           FROM opportunities o
           JOIN accounts a ON a.id = o.account_id
           LEFT JOIN products p ON p.id = o.product_id
           LEFT JOIN users u ON u.id = o.owner_id
           WHERE o.id = ?""",
        (oid,),
    )
    return api_ok(_enrich_opportunity(enriched))


@bp.route("/api/opportunities/<uuid:opp_id>/recalculate", methods=["POST"])
@login_required
def api_recalculate_opportunity(opp_id):
    oid = str(opp_id)
    data = request.get_json(silent=True) or {}
    res = service.recalculate_maturity(
        oid,
        reason=(data.get("reason") or "manual recalculate").strip(),
        changed_by=session.get("user_id"),
        touch_activity=True,
    )
    if not res:
        return api_error("Opportunity not found", 404)

    audit(
        "recalculate",
        "opportunity",
        oid,
        {
            "maturity": [res.get("previous_maturity"), res.get("maturity")],
            "score": [res.get("previous_score"), res.get("maturity_score")],
        },
    )
    return api_ok(res)


@bp.route("/api/opportunities/<uuid:opp_id>", methods=["DELETE"])
@role_required("sales_manager")
def api_delete_opportunity(opp_id):
    oid = str(opp_id)
    existing = query_one("SELECT id, name FROM opportunities WHERE id = ?", (oid,))
    if not existing:
        return api_error("Opportunity not found", 404)

    execute("DELETE FROM opportunities WHERE id = ?", (oid,))
    audit("delete", "opportunity", oid, {"name": existing["name"]})
    return api_ok({"deleted": oid})


# ---------------------------------------------------------------------------
# Analytics & Dormancy Degradation
# ---------------------------------------------------------------------------

@bp.route("/api/analytics", methods=["GET"])
@login_required
def api_analytics():
    opps = query_all(
        """SELECT o.*, a.company_name, u.full_name AS owner_name
           FROM opportunities o
           JOIN accounts a ON a.id = o.account_id
           LEFT JOIN users u ON u.id = o.owner_id"""
    )
    leads = query_all("SELECT id, status FROM leads")
    summary_rows = service.serialize_rows(query_all("SELECT * FROM v_pipeline_summary"))

    open_opps = [o for o in opps if o["stage"] not in ("closed_won", "closed_lost")]
    won_opps = [o for o in opps if o["stage"] == "closed_won"]
    lost_opps = [o for o in opps if o["stage"] == "closed_lost"]

    total_pipeline = round(sum(float(o.get("amount") or 0) for o in open_opps), 2)
    weighted_pipeline = round(sum(float(o.get("weighted_amount") or 0) for o in open_opps), 2)
    won_value = round(sum(float(o.get("amount") or 0) for o in won_opps), 2)
    closed_count = len(won_opps) + len(lost_opps)
    win_rate = round((len(won_opps) / closed_count) * 100.0, 1) if closed_count else 0.0

    now = datetime.now(timezone.utc)
    dormant_opps = []
    for o in open_opps:
        days = service.compute_days_inactive(o.get("last_activity_at"), now=now)
        if days >= service.DEFAULT_DORMANT_DAYS:
            item = service.serialize_row(o)
            item["days_since_activity"] = days
            dormant_opps.append(item)
    dormant_opps.sort(key=lambda x: x["days_since_activity"], reverse=True)

    stage_map = {
        s: {"stage": s, "count": 0, "total_amount": 0.0, "weighted_amount": 0.0}
        for s in service.OPP_STAGES
    }
    for o in opps:
        s = o["stage"]
        if s in stage_map:
            stage_map[s]["count"] += 1
            stage_map[s]["total_amount"] = round(stage_map[s]["total_amount"] + float(o.get("amount") or 0), 2)
            stage_map[s]["weighted_amount"] = round(stage_map[s]["weighted_amount"] + float(o.get("weighted_amount") or 0), 2)

    maturity_map = {
        m: {"maturity": m, "deals": 0, "total_amount": 0.0, "weighted_amount": 0.0}
        for m in service.MATURITY_TIERS
    }
    for r in summary_rows:
        m = r.get("maturity")
        if m in maturity_map:
            maturity_map[m]["deals"] += int(r.get("deals") or 0)
            maturity_map[m]["total_amount"] = round(maturity_map[m]["total_amount"] + float(r.get("total_amount") or 0), 2)
            maturity_map[m]["weighted_amount"] = round(maturity_map[m]["weighted_amount"] + float(r.get("weighted_amount") or 0), 2)

    lead_count = len(leads)
    converted_leads = sum(1 for l in leads if l["status"] == "converted")
    lead_conversion_rate = round((converted_leads / lead_count) * 100.0, 1) if lead_count else 0.0

    recent_history = service.serialize_rows(
        query_all(
            """SELECT h.*, o.name AS opportunity_name, a.company_name, u.full_name AS changed_by_name
               FROM opportunity_history h
               JOIN opportunities o ON o.id = h.opportunity_id
               JOIN accounts a ON a.id = o.account_id
               LEFT JOIN users u ON u.id = h.changed_by
               ORDER BY h.changed_at DESC, h.id DESC
               LIMIT 20"""
        )
    )

    return api_ok(
        {
            "kpis": {
                "open_count": len(open_opps),
                "total_pipeline": total_pipeline,
                "weighted_pipeline": weighted_pipeline,
                "won_count": len(won_opps),
                "won_value": won_value,
                "lost_count": len(lost_opps),
                "win_rate": win_rate,
                "dormant_count": len(dormant_opps),
                "lead_count": lead_count,
                "converted_lead_count": converted_leads,
                "lead_conversion_rate": lead_conversion_rate,
            },
            "by_stage": [stage_map[s] for s in service.OPP_STAGES],
            "by_maturity": [maturity_map[m] for m in service.MATURITY_TIERS],
            "dormant_opportunities": dormant_opps,
            "recent_history": recent_history,
        }
    )


@bp.route("/api/dormancy/run", methods=["POST"])
@role_required("account_manager", "sales_manager")
def api_run_dormancy():
    data = request.get_json(silent=True) or {}
    try:
        days = int(data.get("dormant_days") or service.DEFAULT_DORMANT_DAYS)
    except (TypeError, ValueError):
        return api_error("dormant_days must be an integer")

    result = service.degrade_dormant_opportunities(
        dormant_days=days,
        changed_by=session.get("user_id"),
    )
    audit(
        "dormancy_check",
        "opportunity",
        None,
        {
            "threshold_days": result["threshold_days"],
            "dormant_found": result["dormant_found"],
            "degraded": result["degraded"],
        },
    )
    return api_ok(result)
