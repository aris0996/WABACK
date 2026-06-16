#!/bin/sh
set -e

exec gunicorn "app.main:app" --bind "0.0.0.0:${APP_PORT:-5000}" --workers "${WEB_CONCURRENCY:-1}" --timeout 180
