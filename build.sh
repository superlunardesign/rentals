#!/usr/bin/env bash
# Build script for Render deployment
set -e

echo "=== Installing Python dependencies ==="
pip install -r requirements.txt

echo "=== Installing Playwright Chromium ==="
# Set browser install path to a user-writable location
export PLAYWRIGHT_BROWSERS_PATH=/opt/render/.cache/ms-playwright
mkdir -p $PLAYWRIGHT_BROWSERS_PATH

# Install without --with-deps since Render doesn't allow su/sudo
# Render's environment should have most required libs
playwright install chromium || echo "Warning: Playwright browser install may have issues"

echo "=== Build complete! ==="
