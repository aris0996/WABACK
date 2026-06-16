from flask import Blueprint, render_template

from ..security import login_required

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.get("/")
@login_required
def index():
    return render_template("dashboard.html")
