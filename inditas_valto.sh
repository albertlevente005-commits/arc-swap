#!/usr/bin/env bash
# ARC Swap webapp inditasa (Linux/macOS). Elotte: pip install -r requirements.txt ; cp .env.minta .env
cd "$(dirname "$0")"
exec python3 valto_app.py
