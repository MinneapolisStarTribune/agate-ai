#!/bin/bash
set -e

echo "Starting Celery worker..."
cd /usr/src/app
exec celery -A worker.workflows worker --loglevel=info