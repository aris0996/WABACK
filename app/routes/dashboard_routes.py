from flask import Blueprint, render_template

from ..security import login_required

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.get("/")
@login_required
def index():
    return render_template(
        "pages/overview.html",
        page="overview",
        title="Overview",
        subtitle="Status sistem auto reply dan memory.",
    )


@dashboard_bp.get("/contacts")
@login_required
def contacts_page():
    return render_template(
        "pages/contacts.html",
        page="contacts",
        title="Contacts",
        subtitle="Kelola nomor, auto reply, block AI, chat, dan memory.",
    )


@dashboard_bp.get("/settings")
@login_required
def settings_page():
    return render_template(
        "pages/settings.html",
        page="settings",
        title="Settings",
        subtitle="Konfigurasi WAHA, Ollama, auto reply, allowlist, dan memory.",
    )


@dashboard_bp.get("/diagnostics")
@login_required
def diagnostics_page():
    return render_template(
        "pages/diagnostics.html",
        page="diagnostics",
        title="Diagnostics",
        subtitle="Cek koneksi WAHA, Ollama, GitHub auto-update, dan status Git.",
    )


@dashboard_bp.get("/prompts")
@login_required
def prompts_page():
    return render_template(
        "pages/prompts.html",
        page="prompts",
        title="Prompt Editor",
        subtitle="Prompt runtime tambahan. Personality utama tetap dari Modelfile.",
    )


@dashboard_bp.get("/logs")
@login_required
def logs_page():
    return render_template(
        "pages/logs.html",
        page="logs",
        title="Logs",
        subtitle="Riwayat event sistem, error koneksi, webhook, dan auto update.",
    )
