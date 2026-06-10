#!/bin/bash
set -e

# Start redis server in the background
redis-server --daemonize yes

# Wait a second for redis to boot
sleep 1

# Start celery worker in the background
celery -A app.tasks worker --loglevel=info &

# Start the uvicorn server in the foreground
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
