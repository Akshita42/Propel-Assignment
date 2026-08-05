#!/usr/bin/env bash
# build.sh — Single build script for Render.com deployment
# Builds the React frontend, copies it into backend/static, then installs Python deps.
# Set this as your Render Build Command: bash build.sh

set -e  # Exit immediately on any error

echo "=== [1/3] Building React frontend ==="
cd frontend
npm install --include=optional
npm run build
echo "Frontend build complete. dist/ contents:"
ls -la dist/

echo ""
echo "=== [2/3] Copying frontend dist into backend/static ==="
cd ..
mkdir -p backend/static
cp -r frontend/dist/* backend/static/
echo "Copied. backend/static/ contents:"
ls -la backend/static/

echo ""
echo "=== [3/3] Installing Python dependencies ==="
cd backend
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

echo ""
echo "=== Build complete! ==="
echo "Start command: cd backend && uvicorn app.main:app --host 0.0.0.0 --port \$PORT"
