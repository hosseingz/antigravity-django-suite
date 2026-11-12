---
name: django-docker-scaffold
description: Authoritative blueprint for scaffolding a secure, production-grade Docker infrastructure for Django REST Framework, PostgreSQL, Redis, Celery (with profile isolation), Nginx, and Next.js App Router. Activates when containerizing Django projects, configuring multi-container Docker Compose stacks, or hardening container execution security.
---

# Django Docker Scaffold

This skill provides the production architecture and scaffolding procedures for deploying containerized Django REST Framework backends connected to PostgreSQL, Redis, Celery workers/beat, and Next.js frontend applications behind an Nginx reverse proxy.

---

## 1. Architectural Layout & Networking

```
                              [ Browser / External Client ]
                                           │
                                           ▼ (Port 8080:80)
                             ┌───────────────────────────┐
                             │    Nginx Reverse Proxy    │
                             └─────────────┬─────────────┘
                                           │
                    ┌──────────────────────┴──────────────────────┐
                    │ (Path: /api, /admin, /static, /media)       │ (Path: /)
                    ▼                                             ▼
       ┌─────────────────────────┐                   ┌─────────────────────────┐
       │   Django Backend :8000  │                   │   Next.js Frontend :3000│
       │   (Gunicorn, appuser)   │                   │   (Node SSR, appuser)   │
       └────────────┬────────────┘                   └────────────┬────────────┘
                    │                                             │
      ┌─────────────┼─────────────┐                               │
      │             │             │                               │
      ▼             ▼             ▼                               │
┌───────────┐ ┌───────────┐ ┌───────────┐                         │
│ PostgreSQL│ │   Redis   │ │  Celery   │                         │
│   :5432   │ │   :6379   │ │Worker/Beat│                         │
└───────────┘ └───────────┘ └───────────┘                         │
      ▲                                                           │
      └─────────────────(Internal Docker Bridge)──────────────────┘
                 INTERNAL_API_BASE_URL: http://backend:8000
```

### 1.1 Port Mapping & Network Isolation Rules
- **Public Edge**: Only Nginx binds external host ports (e.g. `8080:80` or `80:80`).
- **Internal Micro-Segmentation**: Services (`db`, `redis`, `backend`, `frontend`) only declare `expose:`, making their ports accessible strictly within `internal_net`. Host machines cannot reach the database or cache directly in production.
- **Development Hot-Reload**: `docker-compose.override.yml` maps ports (`8000:8000`, `3000:3000`, `5432:5432`) to localhost only when developing locally.
- **Dual-Environment URLs**:
  - `INTERNAL_API_BASE_URL=http://backend:8000` (Node.js SSR queries backend via Docker network bridge).
  - `NEXT_PUBLIC_API_BASE_URL=http://localhost:8080` (Browser clients query backend via public gateway).

### 1.2 Environment Modes & Parity Contract
Two orchestration modes are mandatory; a container scaffold that ships only one is incomplete.

| Concern | `docker-compose.yml` (Production-like) | `docker-compose.override.yml` (Development) |
| :--- | :--- | :--- |
| **App Process** | Gunicorn (backend), `node server.js` | `runserver`, `next dev` |
| **Image Target** | `runner` (minimal wheels/standalone artifacts) | `dev` (dependencies + devDependencies installed) |
| **Source Code** | Baked into container image | Bind-mounted; `/app/node_modules` & `.next` shadowed by volumes |
| **Host Ports** | Only public edge (`8080:80`) | Loopback only (`127.0.0.1:8000`, `127.0.0.1:3000`, `127.0.0.1:5432`) |
| **`DEBUG` / `ENVIRONMENT`** | `0` / `production` | `1` / `development` |

- **Never execute a development server from a production standalone image**: A production `runner` stage contains only `.next/standalone` without devDependencies or `node_modules` CLI binaries. Running `next dev` or `runserver` in a production image fails with `sh: next: not found`. Specify a dedicated `dev` target in `Dockerfile.frontend` and select it via `build.target` in `docker-compose.override.yml`.
- **Bind mounts must not mask ownership**: Mounting `./backend:/src` shadows the container's `appuser:appgroup` ownership. Either build with `ARG UID/GID` matching the host developer, or run the dev overlay under `${UID:-1000}:${GID:-1000}`. Never run `chown -R /src` at runtime as it alters host filesystem permissions.

---

## 2. Security Hardening Core Principles

Before scaffolding, review the technical rationale documented in [`security-hardening.md`](./references/security-hardening.md):
- **Base Image**: Uses Debian Slim (`python:3.12-slim-bookworm`) for native `glibc` wheel compatibility (avoiding Alpine's `musl` compilation bottlenecks).
- **Unprivileged Execution**: Mandates `USER appuser` (UID 1001) across all application layers.
- **Signal Handoff (PID 1)**: Entrypoint scripts terminate with `exec "$@"` to avoid the shell process absorbing `SIGTERM`.
- **Zero In-Container `makemigrations`**: Strictly forbidden in entrypoint scripts per [`.agent/rules/ai-guardrails.md`](../../.agent/rules/ai-guardrails.md).
- **Log Rotation**: Bounded to 3 rotated files of 10 MB each to avoid host disk exhaustion.
- **Single-Flight Bootstrap**: `ENTRYPOINT` scripts must not unconditionally run `migrate` and `collectstatic` across all derived containers. Run them once via a dedicated one-shot service, or gate execution via `RUN_BOOTSTRAP=0` in worker/beat containers to avoid concurrent schema write races and corrupting static manifests.
- **Query-Based Database Readiness**: DB readiness probes must execute a query check (`SELECT 1` via psycopg or `pg_isready`), never bare TCP socket connects, ensuring WAL recovery is complete before running migrations.
- **Next.js Build-Time vs. Runtime Variables**: `NEXT_PUBLIC_*` environment variables are baked into JavaScript bundles at `next build` time. They must be supplied via Docker `build.args` rather than runtime `environment:`.
- **Host Line Endings (CRLF Guard)**: Multi-platform projects must enforce LF line endings via `.gitattributes` and inline `sed -i 's/\r$//'` in Dockerfiles for shell entrypoints.

---

## 3. Bundled Resource Templates

The following production-ready templates are available in [`resources/`](./resources):

- [`Dockerfile.backend`](./resources/Dockerfile.backend): Multi-stage build with cached wheel layer, unprivileged user `appuser`, pre-created static/media directories, and health checks.
- [`Dockerfile.frontend`](./resources/Dockerfile.frontend): Multi-stage Next.js standalone container specification with unprivileged user `nextjs`.
- [`entrypoint.sh`](./resources/entrypoint.sh): Signal-safe entrypoint with Python PostgreSQL socket polling (60s timeout), automated asset collection, migrations, and `exec` PID 1 handoff.
- [`docker-compose.yml`](./resources/docker-compose.yml): Production compose definition with database & cache healthchecks, YAML anchors, and isolated Celery worker/beat profiles.
- [`docker-compose.override.yml`](./resources/docker-compose.override.yml): Development overlay with live source mounting and hot reloading.
- [`nginx.conf`](./resources/nginx.conf): Reverse proxy routing static/media volumes, backend APIs, and frontend pages.
- [`.dockerignore`](./resources/.dockerignore): Exhaustive context exclusion list.
- [`.env.example`](./resources/.env.example): Structured, leak-safe environment variables template.

---

## 4. Agent Execution Procedure

When scaffolding or modernizing Docker infrastructure in a target project, follow this exact step-by-step workflow:

### Step 1: Analyze Target Project Layout
Inspect whether the target project uses a monorepo structure:
- Root project directory containing `./backend` and `./frontend`
- If `./backend` does not exist, determine if Django resides at the root level and adjust destination paths accordingly.

### Step 2: Deploy Dockerfiles and Entrypoint
1. Copy [`resources/Dockerfile.backend`](./resources/Dockerfile.backend) into `<target>/backend/Dockerfile`.
2. Copy [`resources/Dockerfile.frontend`](./resources/Dockerfile.frontend) into `<target>/frontend/Dockerfile`.
3. Copy [`resources/entrypoint.sh`](./resources/entrypoint.sh) into `<target>/backend/entrypoint.sh`.
4. Ensure `frontend/public/` exists with a `.gitkeep` (`mkdir -p frontend/public && touch frontend/public/.gitkeep`). The Next.js standalone runner stage executes `COPY --from=builder /app/public ./public`, which fails the build if the directory is missing.
5. Set executable permissions on the entrypoint script:
   ```bash
   chmod +x backend/entrypoint.sh
   ```
6. Verify backend `requirements.txt` contains required production dependencies:
   - `gunicorn>=21.2.0`
   - `psycopg[binary]>=3.1.18` (or `psycopg2-binary>=2.9.9`)
   - `django-environ>=0.11.2`
   - `redis>=5.0.3`
   - `celery>=5.3.6` (if asynchronous tasks are required)

### Step 3: Deploy Orchestration, Reverse Proxy & Environment Templates
1. Copy [`resources/docker-compose.yml`](./resources/docker-compose.yml) into `<target>/docker-compose.yml`.
2. Copy [`resources/docker-compose.override.yml`](./resources/docker-compose.override.yml) into `<target>/docker-compose.override.yml`.
3. Copy [`resources/nginx.conf`](./resources/nginx.conf) into `<target>/nginx/nginx.conf`.
4. Copy [`resources/.dockerignore`](./resources/.dockerignore) into **each build context**:
   - `<target>/.dockerignore`
   - `<target>/backend/.dockerignore`
   - `<target>/frontend/.dockerignore`
5. Copy [`resources/.env.example`](./resources/.env.example) into `<target>/.env.example`.
6. Ensure `.gitattributes` enforces LF line endings across shell and Docker configurations (`*.sh text eol=lf`, `Dockerfile text eol=lf`).

### Step 4: Environment Initialization
Instruct the user (or automate if approved) to generate a local `.env`:
```bash
cp .env.example .env
python -c 'import secrets; print(f"SECRET_KEY={secrets.token_urlsafe(50)}")' >> .env
```
> [!IMPORTANT]
> Step 4 is a hard prerequisite for `docker compose config`. Docker Compose fails validation if `.env` does not exist when referenced by `env_file`.

### Step 5: Validate Container Configuration
Run validation checks in the target workspace:
```bash
test -f .env || { echo "Missing .env — run Step 4 (cp .env.example .env)"; exit 1; }
docker compose config
```
To launch base services without background workers:
```bash
docker compose up -d --build
```
To launch with asynchronous Celery workers enabled:
```bash
docker compose --profile celery up -d --build
```

---

## 5. Troubleshooting & Field Pitfalls

| Issue | Root Cause | Remediation |
| :--- | :--- | :--- |
| `sh: next: not found` in frontend container | Dev server launched from production `runner` (standalone) stage without `node_modules` | Target the `dev` stage in `Dockerfile.frontend` via `docker-compose.override.yml` |
| `COPY failed: ... /app/public: not found` | Next.js scaffold created without `public/` folder | Create `frontend/public/.gitkeep` prior to image build |
| Browser calls `http://backend:8000` or `undefined` | `NEXT_PUBLIC_API_BASE_URL` defined at runtime instead of build time | Pass `NEXT_PUBLIC_API_BASE_URL` via `build.args` in Docker Compose |
| `Permission denied` on `static/` or `media/` in dev | Bind-mounted `./backend` masks container's `appuser` (UID 1001) | Specify `user: "${UID:-1000}:${GID:-1000}"` in dev override |
| `relation ... already exists` on first boot | Entrypoint bootstrap ran concurrently in web and Celery containers | Isolate bootstrap into a one-shot service or set `RUN_BOOTSTRAP=0` in worker containers |
| `FATAL: database system is starting up` | Readiness probe checked bare TCP socket before WAL recovery completed | Use `SELECT 1` query via psycopg or `pg_isready` probe |
| `/entrypoint.sh: no such file or directory` on Linux | Windows CRLF line endings in shell script | Add `.gitattributes` with `eol=lf` and ensure `sed -i 's/\r$//'` in Dockerfile |
```
