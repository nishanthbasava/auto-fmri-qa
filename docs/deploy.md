# Deploying on the lab machine (Docker)

This doubles as the Docker walkthrough — each concept is introduced where this
repo actually uses it.

## The mental model

An **image** is a frozen filesystem + a start command, built once from a
`Dockerfile`. A **container** is a running (disposable) instance of an image.
Anything a container writes to its own filesystem dies with it — which is why
everything we care about (`runs/`, `staged/`, `.env`) lives *outside* the
containers and is attached at start time.

This platform is two images:

| service | image contents | talks to |
|---|---|---|
| `api`   | Python + Chromium + node, the pipeline, FastAPI on :8000 | nobody directly — internal only |
| `web`   | nginx + the built React bundle on :80 | published as :8080, proxies `/api/*` to `api` |

The browser only ever sees one origin (`http://lab-machine:8080`); nginx
forwards `/api/*` over Docker's private network to the api container. The api
container's port is never published to the host, so the password check in
FastAPI is the only door.

## Dockerfile.api, line by line idea

- `FROM python:3.11-slim` — start from a minimal Python filesystem.
- `COPY requirements.txt` + `pip install` **before** copying source: Docker
  caches each instruction as a layer, and a layer is rebuilt only when its
  inputs change. Requirements change rarely, source changes constantly — this
  ordering means a code edit rebuilds in seconds instead of re-downloading
  Chromium every time.
- `playwright install --with-deps chromium` — the figure renderer needs a real
  browser; `--with-deps` also installs its system libraries.
- `npm install pptxgenjs` in `/app` — deck builds shell out to node, and node
  resolves packages by walking up from the script to the nearest
  `node_modules`.
- `COPY pipeline/ agents/ report/ api/` last — the cheap, frequently-changing
  layer.
- `CMD uvicorn api.main:app` — what runs when the container starts. The
  pipeline itself needs no separate service: the API launches it as
  subprocesses inside this same container.

## Dockerfile.web: multi-stage build

Stage 1 (`node:20-slim`) runs `npm install && npm run build` to produce the
static bundle. Stage 2 (`nginx:alpine`) copies **only** `dist/` out of stage 1.
The shipped image contains nginx and ~200 KB of files — no node, no sources.

## docker-compose.yml

Compose is "run these N containers together on a private network, with these
volumes and env": service names become hostnames (nginx reaches the API at
`http://api:8000`), `volumes:` bind host folders into containers
(`./runs:/app/runs` — results survive rebuilds), and `env_file: .env` injects
secrets at runtime so they are never baked into an image. `.dockerignore`
additionally keeps `.env`, `runs/` and `staged/` out of the build context
entirely.

## Runbook

```bash
# 0) one-time: install Docker Desktop (mac) or docker engine + compose (linux)

# 1) secrets -- .env in the repo root (gitignored AND dockerignored):
#      APP_PASSWORD=<shared lab password>
#      ANTHROPIC_API_KEY=sk-ant-...        # only needed for agent figure review

# 2) data -- put a staged fMRIPrep subset in staged/ (from the cluster):
#      python stage_inputs.py /path/to/derivatives -o staged/batch1 --task rest

# 3) build + start (first build ~5-10 min, mostly the Chromium layer):
docker compose up -d --build

# 4) open http://<lab-machine-ip>:8080 from any machine on the lab network,
#    enter the lab password, launch a run.

# observe / operate:
docker compose ps                 # status + health
docker compose logs -f api        # live API + pipeline logs
docker compose restart api
docker compose down               # stop (runs/ and staged/ are untouched)
```

After editing code: `docker compose up -d --build` again — only the changed
layers rebuild.

## ADNI DUA boundary

Keep this on the lab network only: bind on a machine that is not
internet-reachable, never port-forward 8080, and leave the api service
unpublished (it already is). The shared password gates every endpoint, and the
API refuses to start serving without one — but network isolation is the real
control; the password is defense in depth.
