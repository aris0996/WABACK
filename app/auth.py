from hmac import compare_digest

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for

auth_bp = Blueprint("auth", __name__)


@auth_bp.get("/login")
def login():
    if session.get("logged_in"):
        return redirect(url_for("dashboard.index"))
    return render_template("login.html", error="")


@auth_bp.post("/login")
def login_post():
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    if compare_digest(username, current_app.config["ADMIN_USERNAME"]) and compare_digest(
        password, current_app.config["ADMIN_PASSWORD"]
    ):
        session.clear()
        session["logged_in"] = True
        session["username"] = username
        return redirect(url_for("dashboard.index"))
    return render_template("login.html", error="Username atau password salah."), 401


@auth_bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
