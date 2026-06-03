# Stage 1: build React frontend
FROM node:20-alpine AS frontend
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci --silent
COPY frontend/ ./
RUN npm run build

# Stage 2: runtime
FROM python:3.12-slim

WORKDIR /app

# Stockfish from apt — correct arch for the runner, no binary bundling needed
RUN apt-get update && \
    apt-get install -y --no-install-recommends stockfish && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .
COPY --from=frontend /frontend/dist ./frontend/dist

# Cloud Run injects PORT; default 8080
ENV PORT=8080
ENV STOCKFISH_PATH=/usr/games/stockfish

EXPOSE 8080

# Single worker — game state is in-memory, multiple workers would each have their own board
CMD gunicorn server:app --workers 1 --threads 4 --bind "0.0.0.0:${PORT}" --timeout 120
