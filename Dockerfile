# Use python 3.10-slim as base
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV APP_HOME /app

# Set working directory
WORKDIR $APP_HOME

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libssl-dev \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create necessary directories and set permissions
RUN mkdir -p logs data risk/reports \
    && chmod +x scripts/start.sh

# Create a non-root user for security
RUN useradd -m stratex && chown -R stratex:stratex $APP_HOME
USER stratex

# Default command (can be overridden in docker-compose)
CMD ["python", "main.py", "--live"]
