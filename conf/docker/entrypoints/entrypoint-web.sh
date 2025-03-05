#!/bin/bash

echo "Starting Gunicorn..."
cd /usr/src/app
exec gunicorn --bind 0.0.0.0:8000 --timeout 120 --workers 4 --threads 2 --worker-class gthread api.app:app