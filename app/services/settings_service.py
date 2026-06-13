from ..extensions import db
from ..models import AppSetting
from ..seed import DEFAULT_SETTINGS


def get_settings():
    rows = {row.key: row.value for row in AppSetting.query.all()}
    merged = DEFAULT_SETTINGS.copy()
    merged.update(rows)
    return merged


def update_settings(payload):
    allowed = set(DEFAULT_SETTINGS.keys())
    for key, value in payload.items():
        if key not in allowed:
            continue
        row = AppSetting.query.filter_by(key=key).first()
        if not row:
            row = AppSetting(key=key)
            db.session.add(row)
        row.value = "" if value is None else str(value)
    db.session.commit()
    return get_settings()


def setting_bool(value, default=False):
    if value is None:
        return default
    return str(value).lower() in ("1", "true", "yes", "on")
