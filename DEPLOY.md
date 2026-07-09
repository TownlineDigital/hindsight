# Deploying to Render

This repo deploys as a single Docker web service on Render: one container
runs the FastAPI backend, which serves the built React dashboard at
`/dashboard` and runs video-analysis jobs as an in-process background thread
(`backend/jobs.py`) - see `Dockerfile` and `render.yaml` for the concrete
setup, and `ARCHITECTURE_HANDOFF.md` for the reasoning behind these choices
(2026-07-09 hosting decision).

## One-time setup

1. **Push this repo to GitHub** (if you haven't already):
   ```
   git remote add origin https://github.com/<your-username>/<repo-name>.git
   git push -u origin main
   ```
   Create the empty repo on GitHub first (no README/gitignore - this repo
   already has both).

2. **Create a Render account** at https://render.com if you don't have one.

3. **New + → Blueprint**, point it at your GitHub repo. Render reads
   `render.yaml` and sets up the web service, the persistent disk, and
   prompts you for the 5 environment variables marked `sync: false`:
   - `GEMINI_API_KEY` - same value as your local `.env`
   - `SUPABASE_URL` - same value as your local `.env`
   - `SUPABASE_SERVICE_ROLE_KEY` - same value as your local `.env`
   - `VITE_SUPABASE_URL` - same value as your local `frontend/.env`
   - `VITE_SUPABASE_ANON_KEY` - same value as your local `frontend/.env`

   The two `VITE_*` ones get baked into the dashboard's JS bundle at BUILD
   time (Render automatically forwards every env var as a Docker build ARG
   too - see the Dockerfile's own comments), not just read at runtime, so
   they need to be set here even though they're also frontend-only values.

4. First deploy will take a few minutes (installing Tesseract/opencv system
   deps, building the frontend, installing Python deps). Once it's up,
   `https://<your-service>.onrender.com/dashboard/` is the live dashboard.

## Ongoing updates

Once connected, this is the whole loop:
```
# edit code (locally, or via Claude in Cowork)
git add -A
git commit -m "..."
git push
```
Render auto-deploys on every push to `main` (`autoDeploy: true` in
`render.yaml`).

## Known limitations (stated plainly, not hidden)

- **Jobs run as an in-process thread, not a queue.** `backend/jobs.py`
  starts each video-analysis job as a `threading.Thread` inside the same
  process serving HTTP requests. A redeploy that lands while a job is
  mid-analysis kills that one in-flight job - there's no resume. Fine for
  a single always-on instance and occasional redeploys; would need a real
  job queue (e.g. Celery/RQ + Redis, or Render's own background workers) if
  this becomes a real pain point.
- **Raw uploaded videos are not automatically deleted after a job
  finishes.** Frame images get pruned (`prune_unreferenced_frames`, see
  `ARCHITECTURE_HANDOFF.md`), but the source video itself currently isn't -
  worth adding a cleanup step before the persistent disk fills up, since
  video files are large (tens of GB in this project's own local test data).
- **No `frontend/package-lock.json` is committed yet** (deleted locally
  while troubleshooting an unrelated npm/rollup sandbox issue - see
  `ARCHITECTURE_HANDOFF.md`'s 2026-07-09 entry). The Dockerfile falls back
  to `npm install` instead of `npm ci`, which works but isn't fully
  reproducible build-to-build. Regenerate it locally (`cd frontend && npm
  install`) and commit it when convenient.
- **paddleocr/paddlepaddle are intentionally excluded** from the deployed
  image (`requirements-server.txt`) - they're only used by the standalone
  legacy `3_read_ocr.py` script, not the live pipeline.
