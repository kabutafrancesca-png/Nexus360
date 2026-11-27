"""Auth + RBAC. OWNER: Lead.  Roles: sales_rep, account_manager, sales_manager, noc_liaison, executive, admin"""
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash
from app.db import query_one

bp = Blueprint("auth", __name__)


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if not session.get("user_id"):
            return redirect(url_for("auth.login"))
        return view(*a, **kw)
    return wrapped


def role_required(*roles):
    """@role_required('admin', 'sales_manager')"""
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*a, **kw):
            if session.get("role") not in roles and session.get("role") != "admin":
                return "Forbidden", 403
            return view(*a, **kw)
        return wrapped
    return decorator


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = query_one("SELECT * FROM users WHERE email = ? AND is_active", (request.form["email"],))
        if user and check_password_hash(user["password_hash"], request.form["password"]):
            session.update(user_id=str(user["id"]), role=user["role"], full_name=user["full_name"])
            return redirect(url_for("dashboard.index"))
        flash("Invalid credentials")
    return render_template("auth/login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
