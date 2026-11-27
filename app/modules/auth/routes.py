"""Auth + RBAC.  OWNER: Person 1 (Lead).

Provides:
  - login / logout
  - login_required  decorator
  - role_required   decorator
  - change_password page (any logged-in user)
  - /admin/users    page (admin only) — list, create, toggle active, change role
"""
import uuid
from functools import wraps
from flask import (Blueprint, render_template, request,
                   redirect, url_for, session, flash)
from werkzeug.security import check_password_hash, generate_password_hash
from app.db import query_one, query_all, execute
from app.utils import audit

bp = Blueprint("auth", __name__)


# ── Decorators ────────────────────────────────────────────────────────────────

def login_required(view):
    """Redirect to login if the user has no active session."""
    @wraps(view)
    def wrapped(*a, **kw):
        if not session.get("user_id"):
            return redirect(url_for("auth.login"))
        return view(*a, **kw)
    return wrapped


def role_required(*roles):
    """Allow only users whose role is in *roles* (admin always passes).

    Usage:
        @role_required("admin", "sales_manager")
        def my_view(): ...
    """
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*a, **kw):
            if session.get("role") not in roles and session.get("role") != "admin":
                return render_template("auth/forbidden.html"), 403
            return view(*a, **kw)
        return wrapped
    return decorator


# ── Login / Logout ────────────────────────────────────────────────────────────

@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = query_one(
            "SELECT * FROM users WHERE email = ? AND is_active = 1",
            (email,)
        )
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"]   = str(user["id"])
            session["role"]      = user["role"]
            session["full_name"] = user["full_name"]
            session["email"]     = user["email"]
            audit("login", "user", user["id"])
            return redirect(url_for("dashboard.index"))

        flash("Incorrect email or password.")

    return render_template("auth/login.html")


@bp.route("/logout")
def logout():
    if session.get("user_id"):
        audit("logout", "user", session["user_id"])
    session.clear()
    return redirect(url_for("auth.login"))


# ── Change password (any logged-in user) ─────────────────────────────────────

@bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current  = request.form.get("current_password", "")
        new_pw   = request.form.get("new_password", "")
        confirm  = request.form.get("confirm_password", "")

        user = query_one("SELECT * FROM users WHERE id = ?", (session["user_id"],))

        if not check_password_hash(user["password_hash"], current):
            flash("Current password is incorrect.")
        elif len(new_pw) < 8:
            flash("New password must be at least 8 characters.")
        elif new_pw != confirm:
            flash("Passwords do not match.")
        else:
            execute(
                "UPDATE users SET password_hash = ?, updated_at = datetime('now') WHERE id = ?",
                (generate_password_hash(new_pw), session["user_id"])
            )
            audit("update", "user", session["user_id"], {"action": "password_changed"})
            flash("Password updated successfully.")
            return redirect(url_for("dashboard.index"))

    return render_template("auth/change_password.html", title="Change Password")


# ── Admin: User Management ────────────────────────────────────────────────────

ROLES = ["sales_rep", "account_manager", "sales_manager",
         "noc_liaison", "executive", "admin"]


@bp.route("/admin/users")
@role_required("admin")
def admin_users():
    users = query_all("SELECT * FROM users ORDER BY full_name")
    audit("view", "users_list")
    return render_template("auth/admin_users.html", users=users,
                           roles=ROLES, title="User Management")


@bp.route("/admin/users/create", methods=["POST"])
@role_required("admin")
def admin_create_user():
    email     = request.form.get("email", "").strip().lower()
    full_name = request.form.get("full_name", "").strip()
    role      = request.form.get("role", "sales_rep")
    password  = request.form.get("password", "")

    if not email or not full_name or not password:
        flash("Email, name and password are all required.")
        return redirect(url_for("auth.admin_users"))

    if role not in ROLES:
        flash("Invalid role.")
        return redirect(url_for("auth.admin_users"))

    existing = query_one("SELECT id FROM users WHERE email = ?", (email,))
    if existing:
        flash(f"A user with email {email} already exists.")
        return redirect(url_for("auth.admin_users"))

    new_id = str(uuid.uuid4())
    execute(
        """INSERT INTO users (id, email, password_hash, full_name, role)
           VALUES (?, ?, ?, ?, ?)""",
        (new_id, email, generate_password_hash(password), full_name, role)
    )
    audit("create", "user", new_id, {"email": email, "role": role})
    flash(f"User {full_name} created successfully.")
    return redirect(url_for("auth.admin_users"))


@bp.route("/admin/users/<user_id>/toggle", methods=["POST"])
@role_required("admin")
def admin_toggle_user(user_id):
    if user_id == session["user_id"]:
        flash("You cannot deactivate your own account.")
        return redirect(url_for("auth.admin_users"))

    user = query_one("SELECT id, is_active, full_name FROM users WHERE id = ?", (user_id,))
    if not user:
        flash("User not found.")
        return redirect(url_for("auth.admin_users"))

    new_state = 0 if user["is_active"] else 1
    execute(
        "UPDATE users SET is_active = ?, updated_at = datetime('now') WHERE id = ?",
        (new_state, user_id)
    )
    state_label = "activated" if new_state else "deactivated"
    audit("update", "user", user_id, {"is_active": new_state})
    flash(f"{user['full_name']} {state_label}.")
    return redirect(url_for("auth.admin_users"))


@bp.route("/admin/users/<user_id>/role", methods=["POST"])
@role_required("admin")
def admin_change_role(user_id):
    if user_id == session["user_id"]:
        flash("Change your own role via your profile.")
        return redirect(url_for("auth.admin_users"))

    new_role = request.form.get("role", "")
    if new_role not in ROLES:
        flash("Invalid role.")
        return redirect(url_for("auth.admin_users"))

    execute(
        "UPDATE users SET role = ?, updated_at = datetime('now') WHERE id = ?",
        (new_role, user_id)
    )
    audit("update", "user", user_id, {"role": new_role})
    flash("Role updated.")
    return redirect(url_for("auth.admin_users"))


@bp.route("/admin/users/<user_id>/reset-password", methods=["POST"])
@role_required("admin")
def admin_reset_password(user_id):
    new_pw = request.form.get("new_password", "")
    if len(new_pw) < 8:
        flash("Password must be at least 8 characters.")
        return redirect(url_for("auth.admin_users"))

    execute(
        "UPDATE users SET password_hash = ?, updated_at = datetime('now') WHERE id = ?",
        (generate_password_hash(new_pw), user_id)
    )
    audit("update", "user", user_id, {"action": "password_reset_by_admin"})
    flash("Password reset.")
    return redirect(url_for("auth.admin_users"))
