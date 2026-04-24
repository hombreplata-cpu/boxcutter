#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "  BoxCutter"
echo "  ---------------"
echo "  Starting server at http://localhost:5000"
echo "  Press Ctrl+C to stop"
echo ""

python3 "$SCRIPT_DIR/app.py"
