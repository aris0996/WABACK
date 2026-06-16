#!/bin/sh
set -e

exec gunicorn "app.main:app" --bind "0.0.0.0:5000" --workers "${WEB_CONCURRENCY:-2}" --timeout 180
