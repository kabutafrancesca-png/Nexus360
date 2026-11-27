"""Experiential Journey Tracker business logic.  OWNER: Member 3 (Person 3)

Handles:
- Logging engagement events (DC tours, solution demos, executive briefings, etc.) + attendees
- Qualifying-event automation trigger:
    1. Calls pipeline.service.recalculate_maturity(opportunity_id)
    2. Creates a follow-up task with SLA deadline
    3. Sends notifications to sales managers
- SLA overdue task synchronization
"""
from datetime import datetime, timedelta, timezone
import uuid

from app.db import execute, query_all, query_one
from app.modules.pipeline import service as pipeline_service


ENGAGEMENT_TYPES = (
    "dc_tour",
    "solution_demo",
    "event",
    "meeting",
    "call",
    "email",
    "executive_briefing",
)

TASK_STATUSES = ("open", "in_progress", "done", "overdue")

# type -> (default_qualifying, default_maturity_impact, default_sla_hours)
ENGAGEMENT_DEFAULTS = {
    "dc_tour":            (True,  25, 24),
    "executive_briefing": (True,  20, 24),
    "solution_demo":      (True,  18, 48),
    "event":              (True,  10, 72),
    "meeting":            (False,  8, 48),
    "call":               (False,  4, 48),
    "email":              (False,  2, 72),
}

TYPE_LABELS = {
    "dc_tour":            "Data Centre Tour",
    "executive_briefing": "Executive Briefing",
    "solution_demo":      "Solution Demo",
    "event":              "Industry Event",
    "meeting":            "Client Meeting",
    "call":               "Discovery Call",
    "email":              "Email Follow-Up",
}


def sync_overdue_tasks() -> int:
    """Mark open/in-progress tasks whose due_at has passed as overdue."""
    now = datetime.now(timezone.utc)
    open_tasks = query_all(
        """SELECT id, due_at FROM tasks
           WHERE status IN ('open', 'in_progress') AND due_at IS NOT NULL"""
    )
    updated = 0
    for task in open_tasks:
        due = pipeline_service.parse_dt(task.get("due_at"))
        if due and due < now:
            execute("UPDATE tasks SET status = 'overdue' WHERE id = ?", (str(task["id"]),))
            updated += 1
    return updated


def _resolve_event_date(raw_date) -> str:
    if raw_date:
        parsed = pipeline_service.parse_dt(raw_date)
        if parsed:
            return parsed.isoformat(timespec="seconds")
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_engagement(data: dict, facilitator_id: str | None) -> dict:
    """Log an engagement event with attendees and fire qualifying-event triggers."""
    account_id = (data.get("account_id") or "").strip()
    eng_type = (data.get("type") or "").strip()
    if not account_id:
        raise ValueError("account_id is required")
    if eng_type not in ENGAGEMENT_TYPES:
        raise ValueError(f"Invalid engagement type: {eng_type}")

    account = query_one("SELECT id, company_name, owner_id FROM accounts WHERE id = ?", (account_id,))
    if not account:
        raise LookupError("Account not found")

    opportunity_id = (data.get("opportunity_id") or "").strip() or None
    if opportunity_id:
        opp = query_one(
            "SELECT id, account_id, name, owner_id FROM opportunities WHERE id = ?",
            (opportunity_id,),
        )
        if not opp:
            raise LookupError("Opportunity not found")
        if str(opp["account_id"]) != account_id:
            raise ValueError("Opportunity does not belong to the selected account")
    else:
        opp = None

    default_qualifying, default_impact, default_sla = ENGAGEMENT_DEFAULTS[eng_type]
    is_qualifying = bool(data["is_qualifying"]) if "is_qualifying" in data else default_qualifying

    try:
        maturity_impact = int(data["maturity_impact"]) if data.get("maturity_impact") not in (None, "") else default_impact
    except (TypeError, ValueError):
        raise ValueError("maturity_impact must be an integer")
    maturity_impact = max(0, min(60, maturity_impact))

    try:
        sla_hours = int(data["sla_hours"]) if data.get("sla_hours") not in (None, "") else default_sla
    except (TypeError, ValueError):
        raise ValueError("sla_hours must be an integer")
    sla_hours = max(1, min(720, sla_hours))

    title = (data.get("title") or f"{TYPE_LABELS.get(eng_type, eng_type)} — {account['company_name']}").strip()
    tour_type = (data.get("tour_type") or "").strip() or (TYPE_LABELS.get(eng_type) if is_qualifying else None)
    event_date = _resolve_event_date(data.get("event_date"))
    outcome_notes = (data.get("outcome_notes") or "").strip() or None
    follow_up_actions = (data.get("follow_up_actions") or "").strip() or None
    eff_facilitator = (data.get("facilitator_id") or facilitator_id or account.get("owner_id"))

    event_id = str(uuid.uuid4())
    execute(
        """INSERT INTO engagement_events
             (id, account_id, opportunity_id, type, title, tour_type, event_date,
              facilitator_id, outcome_notes, follow_up_actions, is_qualifying, maturity_impact)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event_id,
            account_id,
            opportunity_id,
            eng_type,
            title,
            tour_type,
            event_date,
            eff_facilitator,
            outcome_notes,
            follow_up_actions,
            bool(is_qualifying),
            maturity_impact,
        ),
    )

    # Link attendees (only valid contacts belonging to this account)
    attendee_ids = data.get("attendee_ids") or []
    linked_attendees = []
    seen_contacts = set()
    for cid in attendee_ids:
        cid_str = str(cid).strip()
        if not cid_str or cid_str in seen_contacts:
            continue
        contact = query_one(
            "SELECT id, full_name, job_title, decision_role FROM contacts WHERE id = ? AND account_id = ?",
            (cid_str, account_id),
        )
        if contact:
            seen_contacts.add(cid_str)
            execute(
                "INSERT INTO engagement_attendees (event_id, contact_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
                (event_id, cid_str),
            )
            execute(
                "UPDATE contacts SET last_interaction_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (event_date, cid_str),
            )
            linked_attendees.append(pipeline_service.serialize_row(contact))

    trigger_summary = {
        "fired": False,
        "maturity_update": None,
        "task": None,
        "notifications_sent": 0,
        "next_best_action": "Engagement logged in customer timeline.",
    }

    if is_qualifying:
        trigger_summary["fired"] = True

        # 1. Recalculate opportunity maturity via Pipeline service
        maturity_update = None
        if opportunity_id:
            maturity_update = pipeline_service.recalculate_maturity(
                opportunity_id,
                reason=f"{eng_type} logged",
                changed_by=eff_facilitator,
                touch_activity=True,
            )
            trigger_summary["maturity_update"] = maturity_update

        # 2. Create follow-up task with SLA deadline
        assignee = account.get("owner_id") or (opp.get("owner_id") if opp else None) or eff_facilitator
        due_at = (datetime.now(timezone.utc) + timedelta(hours=sla_hours)).isoformat(timespec="seconds")
        task_id = str(uuid.uuid4())
        task_title = f"Follow up: {title}"
        task_desc = follow_up_actions or (
            f"Send post-{TYPE_LABELS.get(eng_type, eng_type)} summary & next steps to {account['company_name']} "
            f"within {sla_hours}h SLA."
        )
        execute(
            """INSERT INTO tasks
                 (id, title, description, assigned_to, account_id, opportunity_id, event_id,
                  due_at, sla_hours, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
            (
                task_id,
                task_title,
                task_desc,
                str(assignee) if assignee else None,
                account_id,
                opportunity_id,
                event_id,
                due_at,
                sla_hours,
            ),
        )
        task_row = pipeline_service.serialize_row(query_one("SELECT * FROM tasks WHERE id = ?", (task_id,)))
        trigger_summary["task"] = task_row

        # 3. Notify sales managers (fallback to active admins if no sales_manager exists)
        managers = query_all(
            "SELECT id, full_name FROM users WHERE role = 'sales_manager' AND is_active = ?",
            (True,),
        )
        if not managers:
            managers = query_all(
                "SELECT id, full_name FROM users WHERE role = 'admin' AND is_active = ?",
                (True,),
            )

        notif_title = f"Qualifying {TYPE_LABELS.get(eng_type, eng_type)}: {account['company_name']}"
        if maturity_update:
            notif_body = (
                f"{title} completed ({len(linked_attendees)} attendees). "
                f"Deal '{maturity_update['name']}' maturity: "
                f"{maturity_update['previous_maturity'].upper()} ({maturity_update['previous_score']}) -> "
                f"{maturity_update['maturity'].upper()} ({maturity_update['maturity_score']}). "
                f"Follow-up task created with {sla_hours}h SLA."
            )
            trigger_summary["next_best_action"] = (
                f"Deal moved to {maturity_update['maturity'].upper()} ({maturity_update['win_probability']}% win prob). "
                f"Complete SLA follow-up task within {sla_hours}h and advance proposal."
            )
        else:
            notif_body = (
                f"{title} completed for {account['company_name']} ({len(linked_attendees)} attendees). "
                f"Follow-up task created with {sla_hours}h SLA."
            )
            trigger_summary["next_best_action"] = (
                f"Link an active opportunity and complete SLA follow-up task within {sla_hours}h."
            )

        notif_count = 0
        for mgr in managers:
            execute(
                """INSERT INTO notifications (id, user_id, title, body, link, is_read)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), str(mgr["id"]), notif_title, notif_body, "/journey/", False),
            )
            notif_count += 1
        trigger_summary["notifications_sent"] = notif_count

    event_row = pipeline_service.serialize_row(
        query_one(
            """SELECT e.*, a.company_name, o.name AS opportunity_name, u.full_name AS facilitator_name
               FROM engagement_events e
               JOIN accounts a ON a.id = e.account_id
               LEFT JOIN opportunities o ON o.id = e.opportunity_id
               LEFT JOIN users u ON u.id = e.facilitator_id
               WHERE e.id = ?""",
            (event_id,),
        )
    )
    event_row["attendees"] = linked_attendees

    return {
        "event": event_row,
        "attendees": linked_attendees,
        "trigger": trigger_summary,
    }
