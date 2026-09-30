#!/usr/bin/env bash
set -o errexit

npm install
npm run build
uv run python manage.py collectstatic --noinput --ignore=input.css
uv run python manage.py migrate

