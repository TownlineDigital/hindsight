# Multi-stage build: stage 1 builds the React dashboard, stage 2 is the
# actual server that runs at runtime. Keeps Node entirely out of the final
# image - it's only needed to produce frontend/dist, not to serve it (see
# backend/main.py's StaticFiles mount at /dashboard).

# ---- Stage 1: frontend build ----
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend

# frontend/src/lib/supabase.js reads these via import.meta.env - Vite bakes
# them into the JS bundle at BUILD time, not read at runtime like the
# backend's env vars. They must be passed as Docker build args (--build-arg
# or Render's "build-time" env var setting), not just regular runtime env
# vars, or the deployed dashboard will silently fall back to local-dev mode
# (no real sign-in) - see that file's own comments for why.
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL
ENV VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY

# package-lock.json* (with the trailing *) matches whether or not a lockfile
# is present - this repo doesn't have one checked in yet (see the deploy
# instructions), so this falls back to `npm install`. Regenerate and commit
# a real package-lock.json when you get a chance, for reproducible builds.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: the actual server ----
FROM python:3.11-slim AS runtime
WORKDIR /app

ENV PYTHONUNBUFFERED=1

# System-level deps pip alone can't install:
# - tesseract-ocr: pytesseract is just a Python wrapper (see requirements-
#   server.txt) - the real OCR engine ocr_battle_reader.py/
#   battle_text_parser.py call out to has to be a real OS package.
# - libgl1/libglib2.0-0/libsm6/libxext6/libxrender1: opencv-python expects
#   these even in headless/no-display server use - a very common "ImportError:
#   libGL.so.1" crash on slim/minimal base images otherwise.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps BEFORE copying the rest of the app code, so editing
# application code doesn't invalidate this (slow) layer's build cache.
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

# The rest of the pipeline + backend code (.dockerignore keeps this from
# also dragging in videos/jobs/node_modules/tests/etc.)
COPY . .

# Overwrite the checked-in placeholder dashboard build with the real one
# from stage 1.
COPY --from=frontend-builder /app/frontend/dist/. ./backend/static/

# backend/jobs.py's JOBS_DIR = BASE_DIR/"jobs" (BASE_DIR is this WORKDIR,
# since backend/main.py's BASE_DIR = Path(__file__).resolve().parent.parent)
# - mount Render's persistent disk at this exact path so per-job data
# (events.json, frames, uploaded videos) survives restarts and redeploys.
RUN mkdir -p /app/jobs

EXPOSE 8000
# Render sets $PORT itself; ${PORT:-8000} falls back to 8000 for a plain
# `docker run` outside Render (e.g. testing locally).
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
