#!/bin/bash
# One-time setup: creates a local Python environment and installs libraries.
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt
[ -f config.json ] || cp config.example.json config.json
chmod 600 config.json
echo "Fertig. Jetzt config.json ausfüllen (siehe SETUP.md), dann:"
echo "  ./.venv/bin/python fetch.py --login"
