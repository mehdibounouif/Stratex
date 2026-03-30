
FROM python:3.10-slim
 
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV APP_HOME=/app
ENV PYTHONPATH=/app
 
WORKDIR $APP_HOME
 
# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libssl-dev \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
 
# Configure pip: longer timeout + retries so large packages don't drop mid-download
# (scipy is 37MB, numpy is 16MB — they time out on slow connections with defaults)
ENV PIP_DEFAULT_TIMEOUT=120
ENV PIP_RETRIES=5
 
# Install Python dependencies
# --no-cache-dir   → keeps image smaller
# pip-tools is excluded here (dev-only, not needed at runtime)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt
 
# Copy project files
COPY . .
 
# Create runtime directories and set permissions
RUN mkdir -p logs data risk/reports optimization_results \
    && chmod +x scripts/start.sh
 
# Default command (overridden per-service in docker-compose.yml)
CMD ["python", "main.py", "--live"]
