#!/bin/bash
# Doppelklick startet die eBay-Buchhaltung im Browser.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Einrichtung fehlt. Bitte zuerst setup.sh ausführen (siehe SETUP.md)."
  read -n 1 -s -r -p "Taste drücken zum Schließen"
  exit 1
fi
./.venv/bin/python app.py
