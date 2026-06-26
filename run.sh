#!/usr/bin/env bash
# Quick launcher — sets up venv if needed, installs deps, starts Streamlit
set -e

VENV=".venv"

if [ ! -d "$VENV" ]; then
  echo "Creating virtual environment…"
  python3 -m venv "$VENV"
fi

source "$VENV/bin/activate"

echo "Installing / upgrading dependencies…"
pip install -q --upgrade pip
pip install -q -r requirements.txt

if [ ! -f ".env" ]; then
  echo "No .env found — copying .env.example"
  cp .env.example .env
  echo "⚠  Add your XAI_API_KEY to .env before generating docs."
fi

echo "Starting DocAgent…"
streamlit run app.py --server.port 8501
