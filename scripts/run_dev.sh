#!/usr/bin/env bash
# 开发模式：后端 :8000 + 前端热更新 :5173（/api 代理到后端）
set -e
cd "$(dirname "$0")/.."

.venv/bin/python -m uvicorn app.backend.main:app --reload --port 8000 &
BACK=$!
trap 'kill $BACK 2>/dev/null' EXIT

cd app/frontend
npm --cache /tmp/npmcache run dev
