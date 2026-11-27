"""Experiential Journey Tracker module.  OWNER: Member 3 (Person 3)

Implements:
- Log DC tours, solution demos, events, and briefings with multi-contact attendees
- Qualifying-event automation trigger (maturity bump + SLA task + manager notification)
- Engagement history per account & attendance analytics
- Follow-up tasks with SLA tracking + notifications bell
"""
import uuid
from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template, request, session

from app.db import execute, query_all, query_one
from app.modules.auth.routes import login_required
from app.modules.journey import service
from app.modules.pipeline import service as pipeline_service
from app.utils import api_error, api_ok, audit

bp = Blueprint("journey", __name__)


@bp.route("/")
@login_required
def index():
    return render_template("journey/index.html", title="Experiential Journey Tracker")


@bp.route("/api/ping")
@login_required
def ping():
    return api_ok("journey module is wired up")


@bp.route("/api/meta", methods=["GET"])
@login_required
def api_meta():
    accounts = pipeline_service.serialize_rows(
        query_all("SELECT id, company_name, tier, status, owner_id FROM accounts ORDER BY company_name")
    )
    users = pipeline_service.serialize_rows(
        query_all(
            "SELECT id, full_name, email, role FROM users WHERE is_active = ? ORDER BY full_name",
            (True,),
        )
    )
    defaults = {
        k: {"qualifying": v[0], "impact": v[1], "sla_hours": v[2], "label": service.TYPE_LABELS[k]}
        for k, v in service.ENGAGEMENT_DEFAULTS.items()
    }
    return api_ok(
        {
            "accounts": accounts,
            "users": users,
            "engagement_types": list(service.ENGAGEMENT_TYPES),
            "engagement_defaults": defaults,
            "task_statuses": list(service.TASK_STATUSES),
            "current_user": {
                "id": session.get("user_id"),
                "role": session.get("role"),
                "full_name": session.get("full_name"),
            },
        }
    )


@bp.route("/api/accounts/<uuid:account_id>/context", methods=["GET"])
@login_required
def api_account_context(account_id):
    aid = str(account_id)
    account = query_one("SELECT id, company_name, tier, status FROM accounts WHERE id = ?", (aid,))
    if not account:
        return api_error("Account not found", 404)

    contacts = pipeline_service.serialize_rows(
        query_all(
            """SELECT id, full_name, job_title, email, decision_role, sentiment
               FROM contacts
               WHERE account_id = ?
               ORDER BY full_name""",
            (aid,),
        )
    )
    opportunities = pipeline_service.serialize_rows(
        query_all(
            """SELECT id, name, stage, maturity, maturity_score, win_probability, amount
               FROM opportunities
               WHERE account_id = ? AND stage NOT IN ('closed_won', 'closed_lost')
               ORDER BY updated_at DESC""",
            (aid,),
        )
    )
    return api_ok(
        {
            "account": pipeline_service.serialize_row(account),
            "contacts": contacts,
            "opportunities": opportunities,
        }
    )


# ---------------------------------------------------------------------------
# Engagement Events
# ---------------------------------------------------------------------------

@bp.route("/api/engagements", methods=["GET"])
@login_required
def api_list_engagements():
    account_id = request.args.get("account_id", "").strip()
    eng_type = request.args.get("type", "").strip()
    qualifying_only = request.args.get("qualifying_only", "").strip() in ("1", "true", "yes")

    if eng_type and eng_type not in service.ENGAGEMENT_TYPES:
        return api_error(f"Invalid engagement type: {eng_type}")

    clauses = []
    params = []
    if account_id:
        clauses.append("e.account_id = ?")
        params.append(account_id)
    if eng_type:
        clauses.append("e.type = ?")
        params.append(eng_type)
    if qualifying_only:
        clauses.append("e.is_qualifying = ?")
        params.append(True)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    events = pipeline_service.serialize_rows(
        query_all(
            f"""SELECT e.*, a.company_name, o.name AS opportunity_name,
                       o.maturity AS opportunity_maturity, u.full_name AS facilitator_name
                FROM engagement_events e
                JOIN accounts a ON a.id = e.account_id
                LEFT JOIN opportunities o ON o.id = e.opportunity_id
                LEFT JOIN users u ON u.id = e.facilitator_id
                {where}
                ORDER BY e.event_date DESC, e.created_at DESC""",
            tuple(params),
        )
    )

    if events:
        attendee_rows = pipeline_service.serialize_rows(
            query_all(
                """SELECT ea.event_id, c.id, c.full_name, c.job_title, c.decision_role
                   FROM engagement_attendees ea
                   JOIN contacts c ON c.id = ea.contact_id"""
            )
        )
        by_event = {}
        for row in attendee_rows:
            eid = row.pop("event_id")
            by_event.setdefault(eid, []).append(row)
        for ev in events:
            ev["attendees"] = by_event.get(ev["id"], [])

    return api_ok(events)


@bp.route("/api/engagements", methods=["POST"])
@login_required
def api_create_engagement():
    data = request.get_json() or {}
    try:
        result = service.log_engagement(data, facilitator_id=session.get("user_id"))
    except ValueError as exc:
        return api_error(str(exc), 400)
    except LookupError as exc:
        return api_error(str(exc), 404)

    audit(
        "create",
        "engagement_event",
        result["event"]["id"],
        {
            "account_id": result["event"]["account_id"],
            "opportunity_id": result["event"].get("opportunity_id"),
            "type": result["event"]["type"],
            "is_qualifying": bool(result["event"].get("is_qualifying")),
            "attendees": len(result["attendees"]),
            "trigger_fired": result["trigger"]["fired"],
        },
    )
    return api_ok(result), 201


# ---------------------------------------------------------------------------
# Tasks (SLA Follow-Ups)
# ---------------------------------------------------------------------------

@bp.route("/api/tasks", methods=["GET"])
@login_required
def api_list_tasks():
    service.sync_overdue_tasks()

    status = request.args.get("status", "").strip()
    account_id = request.args.get("account_id", "").strip()
    mine = request.args.get("mine", "").strip() in ("1", "true", "yes")

    if status and status not in service.TASK_STATUSES:
        return api_error(f"Invalid task status: {status}")

    clauses = []
    params = []
    if status:
        clauses.append("t.status = ?")
        params.append(status)
    if account_id:
        clauses.append("t.account_id = ?")
        params.append(account_id)
    if mine and session.get("user_id"):
        clauses.append("t.assigned_to = ?")
        params.append(session.get("user_id"))

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = pipeline_service.serialize_rows(
        query_all(
            f"""SELECT t.*, a.company_name, o.name AS opportunity_name,
                       u.full_name AS assignee_name
                FROM tasks t
                LEFT JOIN accounts a ON a.id = t.account_id
                LEFT JOIN opportunities o ON o.id = t.opportunity_id
                LEFT JOIN users u ON u.id = t.assigned_to
                {where}
                ORDER BY
                  CASE t.status WHEN 'overdue' THEN 0 WHEN 'open' THEN 1 WHEN 'in_progress' THEN 2 ELSE 3 END,
                  t.due_at ASC""",
            tuple(params),
        )
    )
    return api_ok(rows)


@bp.route("/api/tasks", methods=["POST"])
@login_required
def api_create_task():
    data = request.get_json() or {}
    title = (data.get("title") or "").strip()
    if not title:
        return api_error("title is required")

    try:
        sla_hours = int(data.get("sla_hours") or 48)
    except (TypeError, ValueError):
        return api_error("sla_hours must be an integer")
    sla_hours = max(1, min(720, sla_hours))

    due_at = data.get("due_at")
    if due_at:
        parsed = pipeline_service.parse_dt(due_at)
        due_iso = parsed.isoformat(timespec="seconds") if parsed else None
    else:
        due_iso = (datetime.now(timezone.utc) + timedelta(hours=sla_hours)).isoformat(timespec="seconds")

    task_id = str(uuid.uuid4())
    assigned_to = data.get("assigned_to") or session.get("user_id")
    account_id = (data.get("account_id") or "").strip() or None
    opportunity_id = (data.get("opportunity_id") or "").strip() or None

    execute(
        """INSERT INTO tasks
             (id, title, description, assigned_to, account_id, opportunity_id, due_at, sla_hours, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
        (
            task_id,
            title,
            (data.get("description") or "").strip() or None,
            assigned_to,
            account_id,
            opportunity_id,
            due_iso,
            sla_hours,
        ),
    )

    row = pipeline_service.serialize_row(
        query_one(
            """SELECT t.*, a.company_name, o.name AS opportunity_name, u.full_name AS assignee_name
               FROM tasks t
               LEFT JOIN accounts a ON a.id = t.account_id
               LEFT JOIN opportunities o ON o.id = t.opportunity_id
               LEFT JOIN users u ON u.id = t.assigned_to
               WHERE t.id = ?""",
            (task_id,),
        )
    )
    audit("create", "task", task_id, {"title": title, "sla_hours": sla_hours})
    return api_ok(row), 201


@bp.route("/api/tasks/<uuid:task_id>", methods=["PATCH"])
@login_required
def api_update_task(task_id):
    tid = str(task_id)
    existing = query_one("SELECT * FROM tasks WHERE id = ?", (tid,))
    if not existing:
        return api_error("Task not found", 404)

    data = request.get_json() or {}
    new_status = (data.get("status") or "").strip()
    if new_status not in service.TASK_STATUSES:
        return api_error(f"Invalid task status: {new_status}")

    completed_at = datetime.now(timezone.utc).isoformat(timespec="seconds") if new_status == "done" else None
    execute(
        "UPDATE tasks SET status = ?, completed_at = ? WHERE id = ?",
        (new_status, completed_at, tid),
    )
    audit("update", "task", tid, {"status": [existing["status"], new_status]})

    updated = pipeline_service.serialize_row(
        query_one(
            """SELECT t.*, a.company_name, o.name AS opportunity_name, u.full_name AS assignee_name
               FROM tasks t
               LEFT JOIN accounts a ON a.id = t.account_id
               LEFT JOIN opportunities o ON o.id = t.opportunity_id
               LEFT JOIN users u ON u.id = t.assigned_to
               WHERE t.id = ?""",
            (tid,),
        )
    )
    return api_ok(updated)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

@bp.route("/api/notifications", methods=["GET"])
@login_required
def api_list_notifications():
    uid = session.get("user_id")
    role = session.get("role")
    scope = request.args.get("scope", "").strip()

    if scope == "all" and role in ("admin", "sales_manager"):
        rows = pipeline_service.serialize_rows(
            query_all(
                """SELECT n.*, u.full_name AS recipient_name
                   FROM notifications n
                   LEFT JOIN users u ON u.id = n.user_id
                   ORDER BY n.created_at DESC
                   LIMIT 50"""
            )
        )
    else:
        rows = pipeline_service.serialize_rows(
            query_all(
                """SELECT n.*, u.full_name AS recipient_name
                   FROM notifications n
                   LEFT JOIN users u ON u.id = n.user_id
                   WHERE n.user_id = ?
                   ORDER BY n.created_at DESC
                   LIMIT 50""",
                (uid,),
            )
        )

    unread_count = sum(1 for r in rows if not r.get("is_read"))
    return api_ok({"items": rows, "unread_count": unread_count})


@bp.route("/api/notifications/<uuid:notif_id>/read", methods=["PATCH"])
@login_required
def api_mark_notification_read(notif_id):
    nid = str(notif_id)
    existing = query_one("SELECT id, user_id FROM notifications WHERE id = ?", (nid,))
    if not existing:
        return api_error("Notification not found", 404)

    if str(existing["user_id"]) != str(session.get("user_id")) and session.get("role") != "admin":
        return api_error("Forbidden", 403)

    execute("UPDATE notifications SET is_read = ? WHERE id = ?", (True, nid))
    return api_ok({"id": nid, "is_read": True})


@bp.route("/api/notifications/read-all", methods=["POST"])
@login_required
def api_mark_all_notifications_read():
    uid = session.get("user_id")
    execute("UPDATE notifications SET is_read = ? WHERE user_id = ? AND NOT is_read", (True, uid))
    return api_ok({"marked_read": True})


# ---------------------------------------------------------------------------
# Engagement & Attendance Analytics
# ---------------------------------------------------------------------------

@bp.route("/api/analytics", methods=["GET"])
@login_required
def api_analytics():
    service.sync_overdue_tasks()

    events = query_all(
        """SELECT e.id, e.account_id, e.type, e.is_qualifying, e.maturity_impact, a.company_name
           FROM engagement_events e
           JOIN accounts a ON a.id = e.account_id"""
    )
    attendees = query_all(
        """SELECT ea.event_id, c.id AS contact_id, c.decision_role
           FROM engagement_attendees ea
           JOIN contacts c ON c.id = ea.contact_id"""
    )
    tasks = query_all("SELECT id, status FROM tasks")

    type_counts = {t: 0 for t in service.ENGAGEMENT_TYPES}
    account_stats = {}
    qualifying_count = 0

    for ev in events:
        etype = ev["type"]
        if etype in type_counts:
            type_counts[etype] += 1
        if ev.get("is_qualifying"):
            qualifying_count += 1
        aid = str(ev["account_id"])
        entry = account_stats.setdefault(
            aid,
            {
                "account_id": aid,
                "company_name": ev["company_name"],
                "events": 0,
                "qualifying_events": 0,
                "attendees": 0,
            },
        )
        entry["events"] += 1
        if ev.get("is_qualifying"):
            entry["qualifying_events"] += 1

    ev_to_acc = {str(ev["id"]): str(ev["account_id"]) for ev in events}
    role_counts = {}
    unique_contacts = set()
    for att in attendees:
        unique_contacts.add(str(att["contact_id"]))
        role = att.get("decision_role") or "user"
        role_counts[role] = role_counts.get(role, 0) + 1
        aid = ev_to_acc.get(str(att["event_id"]))
        if aid and aid in account_stats:
            account_stats[aid]["attendees"] += 1

    task_counts = {s: 0 for s in service.TASK_STATUSES}
    for t in tasks:
        st = t["status"]
        if st in task_counts:
            task_counts[st] += 1

    top_accounts = sorted(
        account_stats.values(),
        key=lambda x: (x["qualifying_events"], x["events"], x["attendees"]),
        reverse=True,
    )[:10]

    return api_ok(
        {
            "kpis": {
                "total_engagements": len(events),
                "qualifying_engagements": qualifying_count,
                "total_attendees": len(attendees),
                "unique_contacts_engaged": len(unique_contacts),
                "open_tasks": task_counts["open"] + task_counts["in_progress"],
                "overdue_tasks": task_counts["overdue"],
                "completed_tasks": task_counts["done"],
            },
            "by_type": [
                {"type": t, "label": service.TYPE_LABELS[t], "count": type_counts[t]}
                for t in service.ENGAGEMENT_TYPES
            ],
            "by_decision_role": [
                {"role": r, "count": c}
                for r, c in sorted(role_counts.items(), key=lambda x: x[1], reverse=True)
            ],
            "task_breakdown": task_counts,
            "top_accounts": top_accounts,
        }
    )
