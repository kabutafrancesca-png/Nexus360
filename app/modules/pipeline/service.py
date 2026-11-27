"""Shared CRM & Pipeline business logic.

Exposes `recalculate_maturity(opportunity_id)` and opportunity lifecycle helpers
used by Pipeline (WP2), Experiential Journey Tracker (WP3), and Cross-Sell (WP5).
"""
from datetime import date, datetime, timezone
from decimal import Decimal
import uuid

from flask import current_app

from app.db import execute, query_all, query_one


LEAD_STATUSES = ("new", "contacted", "qualified", "disqualified", "converted")
LEAD_SOURCES = ("website", "referral", "event", "cold_outreach", "partner", "inbound")

OPP_STAGES = (
    "qualification",
    "discovery",
    "proposal",
    "negotiation",
    "contract_review",
    "closed_won",
    "closed_lost",
)
ACTIVE_STAGES = (
    "qualification",
    "discovery",
    "proposal",
    "negotiation",
    "contract_review",
)
MATURITY_TIERS = ("bronze", "silver", "gold", "platinum")

STAGE_BASE_SCORE = {
    "qualification": 15,
    "discovery": 25,
    "proposal": 42,
    "negotiation": 65,
    "contract_review": 85,
    "closed_won": 100,
    "closed_lost": 0,
}

DEFAULT_DORMANT_DAYS = 14


def _is_sqlite() -> bool:
    url = current_app.config.get("DATABASE_URL") or ""
    return url.startswith("sqlite")


def _serialize_value(val):
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, uuid.UUID):
        return str(val)
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    return val


def serialize_row(row):
    """Convert Postgres/SQLite row values into JSON-safe Python primitives."""
    if row is None:
        return None
    return {k: _serialize_value(v) for k, v in dict(row).items()}


def serialize_rows(rows):
    return [serialize_row(r) for r in (rows or [])]


def parse_dt(value):
    """Parse ISO string or datetime into a timezone-aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(text, fmt)
                    return dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
    return None


def compute_days_inactive(last_activity_at, now=None) -> int:
    dt = parse_dt(last_activity_at)
    if dt is None:
        return 0
    ref = now or datetime.now(timezone.utc)
    return max(0, int((ref - dt).total_seconds() // 86400))


def score_to_maturity(score: int, stage: str | None = None) -> tuple[str, float]:
    """Map a 0-100 maturity score and stage to (maturity_tier, win_probability)."""
    if stage == "closed_won":
        return ("platinum", 100.0)
    if stage == "closed_lost":
        return ("bronze", 0.0)

    s = max(0, min(100, int(round(score))))
    if s < 30:
        return ("bronze", round(10.0 + (s / 29.0) * 10.0, 2))
    if s < 60:
        return ("silver", round(30.0 + ((s - 30) / 29.0) * 20.0, 2))
    if s < 80:
        return ("gold", round(60.0 + ((s - 60) / 19.0) * 15.0, 2))
    return ("platinum", round(80.0 + ((s - 80) / 20.0) * 15.0, 2))


def _compute_maturity_components(opp: dict, touch_activity: bool = True) -> tuple[int, str, float]:
    stage = opp.get("stage") or "qualification"
    base = STAGE_BASE_SCORE.get(stage, 15)

    eng_row = query_one(
        """SELECT COALESCE(SUM(maturity_impact), 0) AS total_impact
           FROM engagement_events
           WHERE opportunity_id = ? AND is_qualifying = ?""",
        (str(opp["id"]), True),
    )
    engagement_bonus = min(45, int(float((eng_row or {}).get("total_impact") or 0)))

    committee_row = query_one(
        """SELECT COUNT(*) AS cnt
           FROM engagement_events ee
           JOIN engagement_attendees ea ON ea.event_id = ee.id
           JOIN contacts c ON c.id = ea.contact_id
           WHERE ee.opportunity_id = ?
             AND ee.is_qualifying = ?
             AND c.decision_role IN ('economic_buyer', 'champion')""",
        (str(opp["id"]), True),
    )
    committee_bonus = 5 if int((committee_row or {}).get("cnt") or 0) > 0 else 0

    dormancy_penalty = 0
    if not touch_activity:
        days_inactive = compute_days_inactive(opp.get("last_activity_at"))
        if days_inactive >= DEFAULT_DORMANT_DAYS:
            dormancy_penalty = min(40, (days_inactive // DEFAULT_DORMANT_DAYS) * 10)

    raw_score = base + engagement_bonus + committee_bonus - dormancy_penalty
    new_score = max(0, min(100, int(round(raw_score))))
    new_maturity, new_win_prob = score_to_maturity(new_score, stage)
    return new_score, new_maturity, new_win_prob


def recalculate_maturity(
    opportunity_id,
    reason: str = "recalculate",
    changed_by=None,
    touch_activity: bool = True,
    record_history: bool = True,
):
    """Recalculate maturity tier, score, and win probability for an opportunity.

    Returns the serialized opportunity dict augmented with previous_* fields and
    a `changed` boolean, or None if the opportunity does not exist.
    """
    opp_id = str(opportunity_id)
    opp = query_one("SELECT * FROM opportunities WHERE id = ?", (opp_id,))
    if not opp:
        return None

    old_maturity = opp["maturity"]
    old_score = int(opp["maturity_score"] or 0)
    old_win_prob = float(opp["win_probability"] or 0)
    stage = opp["stage"]

    if stage in ("closed_won", "closed_lost"):
        res = serialize_row(opp)
        res.update(
            previous_maturity=old_maturity,
            previous_score=old_score,
            previous_win_probability=old_win_prob,
            changed=False,
        )
        return res

    new_score, new_maturity, new_win_prob = _compute_maturity_components(
        opp, touch_activity=touch_activity
    )
    amount = float(opp.get("amount") or 0)
    weighted = round(amount * new_win_prob / 100.0, 2)

    sets = [
        "maturity = ?",
        "maturity_score = ?",
        "win_probability = ?",
        "updated_at = CURRENT_TIMESTAMP",
    ]
    params = [new_maturity, new_score, new_win_prob]

    if _is_sqlite():
        sets.append("weighted_amount = ?")
        params.append(weighted)

    if touch_activity:
        sets.append("last_activity_at = CURRENT_TIMESTAMP")

    params.append(opp_id)
    execute(f"UPDATE opportunities SET {', '.join(sets)} WHERE id = ?", tuple(params))

    changed = (new_maturity != old_maturity) or (new_score != old_score)
    if record_history and changed:
        execute(
            """INSERT INTO opportunity_history
                 (opportunity_id, from_stage, to_stage, from_maturity, to_maturity, reason, changed_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (opp_id, stage, stage, old_maturity, new_maturity, reason, changed_by),
        )

    updated = serialize_row(query_one("SELECT * FROM opportunities WHERE id = ?", (opp_id,)))
    updated.update(
        previous_maturity=old_maturity,
        previous_score=old_score,
        previous_win_probability=old_win_prob,
        changed=changed,
    )
    return updated


def create_opportunity(
    account_id,
    name: str,
    amount: float = 0,
    stage: str = "qualification",
    product_id=None,
    lead_id=None,
    expected_close=None,
    owner_id=None,
    reason: str = "created",
    changed_by=None,
):
    """Create an opportunity with consistent maturity grading and history entry."""
    if stage not in OPP_STAGES:
        raise ValueError(f"Invalid stage: {stage}")

    opp_id = str(uuid.uuid4())
    amt = max(0.0, float(amount or 0))
    init_score = STAGE_BASE_SCORE.get(stage, 15)
    maturity, win_prob = score_to_maturity(init_score, stage)
    weighted = round(amt * win_prob / 100.0, 2)
    closed_at = datetime.now(timezone.utc).isoformat(timespec="seconds") if stage in ("closed_won", "closed_lost") else None

    if _is_sqlite():
        execute(
            """INSERT INTO opportunities
                 (id, account_id, lead_id, product_id, name, stage, maturity,
                  maturity_score, win_probability, amount, weighted_amount,
                  expected_close, owner_id, closed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                opp_id,
                str(account_id),
                str(lead_id) if lead_id else None,
                int(product_id) if product_id else None,
                name.strip(),
                stage,
                maturity,
                init_score,
                win_prob,
                amt,
                weighted,
                expected_close or None,
                str(owner_id) if owner_id else None,
                closed_at,
            ),
        )
    else:
        execute(
            """INSERT INTO opportunities
                 (id, account_id, lead_id, product_id, name, stage, maturity,
                  maturity_score, win_probability, amount,
                  expected_close, owner_id, closed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                opp_id,
                str(account_id),
                str(lead_id) if lead_id else None,
                int(product_id) if product_id else None,
                name.strip(),
                stage,
                maturity,
                init_score,
                win_prob,
                amt,
                expected_close or None,
                str(owner_id) if owner_id else None,
                closed_at,
            ),
        )

    execute(
        """INSERT INTO opportunity_history
             (opportunity_id, from_stage, to_stage, from_maturity, to_maturity, reason, changed_by)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (opp_id, None, stage, None, maturity, reason, str(changed_by) if changed_by else owner_id),
    )

    return serialize_row(query_one("SELECT * FROM opportunities WHERE id = ?", (opp_id,)))


def update_opportunity_stage(
    opportunity_id,
    new_stage: str,
    changed_by=None,
    lost_reason: str | None = None,
    reason: str = "stage_change",
):
    """Transition an opportunity to a new stage, update maturity, and log history."""
    if new_stage not in OPP_STAGES:
        raise ValueError(f"Invalid stage: {new_stage}")

    opp_id = str(opportunity_id)
    opp = query_one("SELECT * FROM opportunities WHERE id = ?", (opp_id,))
    if not opp:
        return None

    old_stage = opp["stage"]
    old_maturity = opp["maturity"]

    if new_stage in ("closed_won", "closed_lost"):
        new_score = 100 if new_stage == "closed_won" else 0
        new_maturity, new_win_prob = score_to_maturity(new_score, new_stage)
        amt = float(opp.get("amount") or 0)
        weighted = round(amt * new_win_prob / 100.0, 2)

        sets = [
            "stage = ?",
            "maturity = ?",
            "maturity_score = ?",
            "win_probability = ?",
            "lost_reason = ?",
            "closed_at = CURRENT_TIMESTAMP",
            "last_activity_at = CURRENT_TIMESTAMP",
            "updated_at = CURRENT_TIMESTAMP",
        ]
        params = [
            new_stage,
            new_maturity,
            new_score,
            new_win_prob,
            lost_reason if new_stage == "closed_lost" else None,
        ]
        if _is_sqlite():
            sets.append("weighted_amount = ?")
            params.append(weighted)
        params.append(opp_id)
        execute(f"UPDATE opportunities SET {', '.join(sets)} WHERE id = ?", tuple(params))

        if new_stage != old_stage or new_maturity != old_maturity:
            execute(
                """INSERT INTO opportunity_history
                     (opportunity_id, from_stage, to_stage, from_maturity, to_maturity, reason, changed_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (opp_id, old_stage, new_stage, old_maturity, new_maturity, reason, changed_by),
            )
        res = serialize_row(query_one("SELECT * FROM opportunities WHERE id = ?", (opp_id,)))
        res.update(previous_stage=old_stage, previous_maturity=old_maturity)
        return res

    # Active stage: update stage + clear closed_at, then recalculate maturity cleanly
    execute(
        """UPDATE opportunities
           SET stage = ?, lost_reason = NULL, closed_at = NULL,
               last_activity_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (new_stage, opp_id),
    )
    updated = recalculate_maturity(
        opp_id,
        reason=reason,
        changed_by=changed_by,
        touch_activity=True,
        record_history=False,
    )
    if new_stage != old_stage or updated["maturity"] != old_maturity:
        execute(
            """INSERT INTO opportunity_history
                 (opportunity_id, from_stage, to_stage, from_maturity, to_maturity, reason, changed_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (opp_id, old_stage, new_stage, old_maturity, updated["maturity"], reason, changed_by),
        )
    updated["previous_stage"] = old_stage
    return updated


def degrade_dormant_opportunities(dormant_days: int = DEFAULT_DORMANT_DAYS, changed_by=None) -> dict:
    """Degrade maturity scores for open opportunities inactive for >= dormant_days."""
    threshold = max(1, int(dormant_days or DEFAULT_DORMANT_DAYS))
    open_opps = query_all(
        """SELECT id, name, stage, maturity, maturity_score, last_activity_at
           FROM opportunities
           WHERE stage NOT IN ('closed_won', 'closed_lost')"""
    )

    dormant_items = []
    degraded_count = 0
    now = datetime.now(timezone.utc)

    for opp in open_opps:
        days_inactive = compute_days_inactive(opp.get("last_activity_at"), now=now)
        if days_inactive >= threshold:
            res = recalculate_maturity(
                opp["id"],
                reason=f"dormant {days_inactive}d",
                changed_by=changed_by,
                touch_activity=False,
                record_history=True,
            )
            if res and res.get("changed"):
                degraded_count += 1
            dormant_items.append(
                {
                    "id": str(opp["id"]),
                    "name": opp["name"],
                    "days_inactive": days_inactive,
                    "previous_maturity": res.get("previous_maturity") if res else opp["maturity"],
                    "new_maturity": res.get("maturity") if res else opp["maturity"],
                    "previous_score": res.get("previous_score") if res else opp["maturity_score"],
                    "new_score": res.get("maturity_score") if res else opp["maturity_score"],
                    "changed": bool(res and res.get("changed")),
                }
            )

    return {
        "checked": len(open_opps),
        "dormant_found": len(dormant_items),
        "degraded": degraded_count,
        "threshold_days": threshold,
        "items": dormant_items,
    }
