#!/usr/bin/env bash
# Build script for Render deployment
set -e

echo "=== Installing Python dependencies ==="
pip install -r requirements.txt

echo "=== Installing Playwright Chromium browser ==="
python -m playwright install chromium

echo "=== Installing Playwright system dependencies ==="
python -m playwright install-deps chromium || echo "Warning: Could not install system deps (may already be present)"

echo "=== Build complete! ==="
