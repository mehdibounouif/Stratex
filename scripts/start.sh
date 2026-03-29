#!/bin/bash
# Stratex Startup Script
cd /app
# Ensure data and logs directories exist
mkdir -p data logs risk/reports


# Execute the command passed to the script
echo "Starting Stratex: $@"
exec "$@"
