#!/usr/bin/env bash
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env
echo "Open http://localhost:8000 in your browser. Press Ctrl+C to stop."
python -m uvicorn app.main:app --port 8000
