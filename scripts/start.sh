#!/bin/bash
# Stratex Startup Script

# Ensure data and logs directories exist
mkdir -p data logs risk/reports

# Initialize database if it's the first run
# Check if the SQLite file exists or run a setup script
if [ ! -f "data/trading.db" ]; then
    echo "First run: Initializing database..."
    python -c "from data.database import init_db; init_db()"
fi

# Execute the command passed to the script
echo "Starting Stratex: $@"
exec "$@"
