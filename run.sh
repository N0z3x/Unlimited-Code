#!/bin/bash
set -e
source .venv/bin/activate 2>/dev/null || true
python unlimited_code.py "$@"