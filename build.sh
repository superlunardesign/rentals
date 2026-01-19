#!/usr/bin/env bash
# Build script for Render deployment
set -e

echo "=== Installing Python dependencies ==="
pip install -r requirements.txt

echo "=== Installing Playwright Firefox ==="
# Set browser install path to a user-writable location
export PLAYWRIGHT_BROWSERS_PATH=/opt/render/.cache/ms-playwright
mkdir -p $PLAYWRIGHT_BROWSERS_PATH

# Firefox has fewer system dependencies than Chromium
# Install without --with-deps since Render doesn't allow su/sudo
playwright install firefox || echo "Warning: Playwright Firefox install may have issues"

# Also try chromium as fallback
echo "=== Installing Playwright Chromium (fallback) ==="
playwright install chromium || echo "Note: Chromium install had issues (common on Render)"

echo "=== Build complete! ==="
