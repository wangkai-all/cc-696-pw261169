#!/usr/bin/env bash
# 生产模式：构建前端后由 FastAPI 单进程托管（:8000）
set -e
cd "$(dirname "$0")/.."

(cd app/frontend && npm --cache /tmp/npmcache install --no-audit --no-fund && npm --cache /tmp/npmcache run build)
exec .venv/bin/python -m uvicorn app.backend.main:app --port 8000
