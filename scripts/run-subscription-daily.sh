#!/bin/bash
# Installed root-owned at /usr/local/lib/radar; no .env or API credentials loaded.
set -euo pipefail
systemctl start radar-subscription-analysis.service
/usr/bin/python3 /usr/local/lib/radar/run-subscription-analysis.py save
