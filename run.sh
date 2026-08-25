#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "[!] ffmpeg not found. Install it first: sudo apt install ffmpeg (or brew install ffmpeg)"
fi

if [ ! -d .venv ]; then
    echo "First run: creating a private Python environment..."
    python3 -m venv .venv
fi

. .venv/bin/activate

if ! python -c "import gradio" >/dev/null 2>&1; then
    echo "Installing dependencies - this only happens once..."
    pip install --upgrade pip
    pip install -r requirements.txt
fi

echo "Starting ClipStitch at http://127.0.0.1:7860 ..."
python -m clipstitch.app
