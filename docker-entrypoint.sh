#!/bin/bash
set -e

cd /app/backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

cd /app/frontend
node server.js &
FRONTEND_PID=$!

trap 'kill -TERM $BACKEND_PID $FRONTEND_PID 2>/dev/null' SIGTERM SIGINT

wait -n $BACKEND_PID $FRONTEND_PID
EXIT_STATUS=$?

kill -TERM $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
exit $EXIT_STATUS
