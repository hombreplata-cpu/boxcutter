#!/usr/bin/env bash
set -e

echo ""
echo "  rekordbox-tools — macOS installer"
echo "  -----------------------------------"

# Python check
if ! command -v python3 &>/dev/null; then
    echo ""
    echo "  ERROR: python3 not found."
    echo "  Install Python 3.9+ from https://www.python.org/downloads/"
    echo "  or via Homebrew: brew install python"
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 9 ]; }; then
    echo ""
    echo "  ERROR: Python $PY_VER found, but 3.9 or higher is required."
    echo "  Download the latest Python from https://www.python.org/downloads/"
    exit 1
fi

echo "  Python $PY_VER — OK"

# Install dependencies
echo ""
echo "  Installing Python dependencies..."
pip3 install flask pyrekordbox mutagen

# SQLCipher setup
echo ""
echo "  Setting up SQLCipher (needed to read the Rekordbox database)..."
if python3 -m pyrekordbox install-sqlcipher; then
    echo "  SQLCipher — OK"
else
    echo ""
    echo "  SQLCipher setup failed. This is common on Apple Silicon (M1/M2/M3)."
    echo ""
    echo "  Fix: install SQLCipher via Homebrew, then re-run this installer."
    echo ""
    echo "    1. Install Homebrew if you don't have it:"
    echo "       /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    echo ""
    echo "    2. Install SQLCipher:"
    echo "       brew install sqlcipher"
    echo ""
    echo "    3. Re-run this installer:"
    echo "       ./install.sh"
    echo ""
    exit 1
fi

echo ""
echo "  Installation complete."
echo "  Run ./start.sh to launch rekordbox-tools."
echo ""
