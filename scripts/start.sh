#!/bin/bash
# Stratex Startup Script

cd /app

mkdir -p data logs risk/reports

echo "Starting Stratex: $@"
exec "$@"
