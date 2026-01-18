#!/usr/bin/env bash
# Build script for Render deployment
set -e

echo "=== Installing Python dependencies ==="
pip install -r requirements.txt

echo "=== Build complete! ==="
