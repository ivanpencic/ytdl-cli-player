#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

if [ ! -f "env/bin/python" ] || ! env/bin/python -m pip --version &>/dev/null; then
    echo "Creating virtual environment..."
    rm -rf env
    python3 -m venv env
    env/bin/python -m ensurepip --upgrade
fi

NEED_INSTALL=false

check_pkg() {
    env/bin/python -c "import $1" 2>/dev/null || NEED_INSTALL=true
}

check_pkg textual
check_pkg yt_dlp

if [ "$NEED_INSTALL" = true ]; then
    echo "Installing dependencies..."
    env/bin/python -m pip install textual yt-dlp
else
    echo "Dependencies already installed."
fi

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffplay >/dev/null 2>&1; then
    echo "Installing ffmpeg..."
    sudo apt install -y ffmpeg
fi
