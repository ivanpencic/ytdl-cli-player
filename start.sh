#!/usr/bin/env bash
cd "$(dirname "$0")"

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffplay >/dev/null 2>&1; then
    echo "ERROR: ffmpeg not found on the system."
    echo "Required for audio conversion and playback."
    echo "Install it with:"
    echo "  sudo apt install ffmpeg   # Debian/Ubuntu"
    echo "  sudo pacman -S ffmpeg     # Arch"
    echo "  sudo dnf install ffmpeg   # Fedora"
    exit 1
fi

exec env/bin/python player.py
