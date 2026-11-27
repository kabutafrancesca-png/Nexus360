import json
from flask import request, session
from app.db import execute


def audit(action, entity, entity_id=None, changes=None):
    """Write an immutable audit log row. Call on every create/update/delete/view of sensitive data.

    audit("update", "account", account_id, {"status": ["active", "at_risk"]})
    """
    execute(
        """INSERT INTO audit_logs (user_id, action, entity_type, entity_id, changes, ip_address)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (session.get("user_id"), action, entity, str(entity_id) if entity_id else None,
         json.dumps(changes or {}), request.remote_addr),
    )


def api_ok(data=None, **extra):
    from flask import jsonify
    return jsonify({"ok": True, "data": data, **extra})


def api_error(message, status=400):
    from flask import jsonify
    return jsonify({"ok": False, "error": message}), status
