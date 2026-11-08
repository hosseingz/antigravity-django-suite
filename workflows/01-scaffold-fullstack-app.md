# Workflow 01: Scaffold Fullstack Application

Step-by-step orchestrator runbook for spinning up a fresh, production-grade Django REST Framework + Next.js App Router + Docker stack from scratch without human intervention.

---

## 1. Architectural Overview & Execution Pipeline

This workflow automates the greenfield scaffolding of an enterprise-grade fullstack application. It sequentially activates three foundational skills in strict dependency order:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Execution Pipeline                             │
└────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Phase 1: Docker Infrastructure (django-docker-scaffold)               │
│ - Deploy multi-stage Dockerfiles & entrypoint.sh                       │
│ - Configure docker-compose.yml & service network isolation             │
│ - Generate root environment template (.env.example -> .env)           │
└────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Phase 2: Django Core Architecture (django-core-architecture)           │
│ - Scaffold backend/ directory with config/ orchestration namespace     │
│ - Inject apps/ directory dynamically into sys.path                     │
│ - Configure 12-factor django-environ, WhiteNoise, and healthcheck     │
└────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Phase 3: Next.js API Synchronization (nextjs-api-sync)                │
│ - Configure dual-environment base URLs (SSR internal vs CSR public)   │
│ - Deploy browser-only Axios client with CSRF injection & mutex locks   │
│ - Deploy RSC-exclusive serverFetch utility with cookie forwarding      │
└────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Phase 4: Container Spin-up & Automated Verification Checklist          │
│ - Execute database migrations and seed container health probes        │
│ - Validate non-root execution, PID 1 signal handoff, and HTTP routing  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Skill Activation Sequence

### Phase 1: Activate `django-docker-scaffold`
**Reference Skill**: [`skills/django-docker-scaffold/SKILL.md`](../skills/django-docker-scaffold/SKILL.md)

1. **Create Project Directory Hierarchy**:
   ```bash
   mkdir -p backend frontend nginx
   ```

2. **Deploy Container Configuration Files**:
   Copy the following templates from [`skills/django-docker-scaffold/resources/`](../skills/django-docker-scaffold/resources/) to the workspace root:
   - `docker-compose.yml` -> `./docker-compose.yml`
   - `docker-compose.override.yml` -> `./docker-compose.override.yml`
   - `nginx.conf` -> `nginx/nginx.conf`
   - `.dockerignore` -> `./.dockerignore`
   - `.env.example` -> `./.env.example`
   - `Dockerfile.backend` -> `backend/Dockerfile`
   - `Dockerfile.frontend` -> `frontend/Dockerfile`
   - `entrypoint.sh` -> `backend/entrypoint.sh`

3. **Initialize Environment Variables**:
   ```bash
   cp .env.example .env
   ```
   Generate cryptographically secure secrets for `SECRET_KEY` and `POSTGRES_PASSWORD` using Python:
   ```bash
   python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(50))" >> .env
   ```
   Ensure `.env` contains the required network configuration keys:
   ```env
   POSTGRES_DB=app_db
   POSTGRES_USER=app_user
   POSTGRES_PASSWORD=generate_secure_password_here
   POSTGRES_HOST=db
   POSTGRES_PORT=5432

   REDIS_URL=redis://redis:6379/1

   SECRET_KEY=generate_secure_key_here
   DEBUG=0
   ALLOWED_HOSTS=localhost,127.0.0.1,backend
   DJANGO_SETTINGS_MODULE=config.settings

   CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8080
   CSRF_TRUSTED_ORIGINS=http://localhost:3000,http://localhost:8080

   INTERNAL_API_BASE_URL=http://backend:8000
   NEXT_PUBLIC_API_BASE_URL=http://localhost:8080
   ```

4. **Set POSIX Permissions**:
   Ensure `backend/entrypoint.sh` is executable:
   ```bash
   chmod +x backend/entrypoint.sh
   ```

---

### Phase 2: Activate `django-core-architecture`
**Reference Skill**: [`skills/django-core-architecture/SKILL.md`](../skills/django-core-architecture/SKILL.md)

1. **Scaffold Django Layout**:
   Create the decoupled directory layout inside `backend/`:
   ```bash
   mkdir -p backend/config backend/apps
   ```

2. **Deploy Core Architecture Templates**:
   Copy the following templates from [`skills/django-core-architecture/resources/`](../skills/django-core-architecture/resources/):
   - `manage.py` -> `backend/manage.py`
   - `settings.py` -> `backend/config/settings.py`
   - `urls.py` -> `backend/config/urls.py`
   - `wsgi.py` -> `backend/config/wsgi.py`
   - `asgi.py` -> `backend/config/asgi.py`
   - `apps_init.py` -> `backend/apps/__init__.py`

3. **Verify Python Dependencies**:
   Create `backend/requirements.txt` with essential production dependencies:
   ```text
   Django>=5.0,<5.2
   djangorestframework>=3.15.0
   django-cors-headers>=4.3.1
   django-environ>=0.11.2
   whitenoise>=6.6.0
   psycopg[binary]>=3.1.18
   redis>=5.0.3
   gunicorn>=21.2.0
   uvicorn>=0.29.0
   ```

4. **Verify Dynamic Syspath Injection**:
   Inspect `backend/config/settings.py` to confirm `apps/` is prepended to `sys.path`:
   ```python
   APPS_DIR = os.path.join(BASE_DIR, "apps")
   if APPS_DIR not in sys.path:
       sys.path.insert(0, APPS_DIR)
   ```
   This ensures modular domain apps located in `backend/apps/<app_name>` are registered by their canonical name (`'<app_name>'`) rather than with prefix pollution (`'apps.<app_name>'`).

5. **Verify WhiteNoise Middleware Placement**:
   Inspect `MIDDLEWARE` in `backend/config/settings.py` to confirm `whitenoise.middleware.WhiteNoiseMiddleware` is situated immediately below `django.middleware.security.SecurityMiddleware`.

---

### Phase 3: Activate `nextjs-api-sync`
**Reference Skill**: [`skills/nextjs-api-sync/SKILL.md`](../skills/nextjs-api-sync/SKILL.md)

1. **Initialize Next.js App Router (if not already initialized)**:
   In `frontend/`, ensure Next.js 14+ or 15+ App Router is configured with TypeScript and Tailwind CSS:
   ```bash
   # When bootstrapping fresh
   npx create-next-app@latest frontend --typescript --tailwind --eslint --app --src-dir=false --import-alias="@/*"
   ```
   Deploy the production frontend Dockerfile:
   - Copy [`skills/django-docker-scaffold/resources/Dockerfile.frontend`](../skills/django-docker-scaffold/resources/Dockerfile.frontend) -> `frontend/Dockerfile`
   In `frontend/next.config.js` (or `next.config.mjs` / `next.config.ts`), configure `output: 'standalone'` to support containerized standalone execution.

2. **Install Frontend HTTP Client**:
   ```bash
   cd frontend && npm install axios
   ```

3. **Deploy API Synchronization Layer**:
   Create the destination directory:
   ```bash
   mkdir -p frontend/lib/api
   ```
   Copy synchronization resources from [`skills/nextjs-api-sync/resources/`](../skills/nextjs-api-sync/resources/) into `frontend/lib/api/`:
   - `apiConfig.ts` -> `frontend/lib/api/apiConfig.ts`
   - `apiClient.ts` -> `frontend/lib/api/apiClient.ts`
   - `serverFetch.ts` -> `frontend/lib/api/serverFetch.ts`
   - `errorUtils.ts` -> `frontend/lib/api/errorUtils.ts`

4. **Enforce Execution Boundaries**:
   Verify that frontend modules respect runtime boundaries:
   - Client components and custom hooks (`'use client'`) must consume `apiClient` from `frontend/lib/api/apiClient.ts`.
   - React Server Components (RSC) and Server Actions must consume `serverFetch` from `frontend/lib/api/serverFetch.ts`.
   - Never import `apiClient.ts` inside Server Components (prevents referencing browser-only globals like `document.cookie` or `window`).

---

## 3. Container Build & Orchestration

1. **Verify Docker Compose Configuration**:
   ```bash
   docker compose config
   ```
   Ensure no syntax errors, port collisions, or missing environment variables exist.

2. **Build and Launch Containerized Stack**:
   ```bash
   docker compose up --build -d
   ```

3. **Inspect Initial Service Status**:
   ```bash
   docker compose ps
   ```
   All primary services (`db`, `redis`, `backend`, `frontend`, `nginx`) should report `running` or `healthy`.

---

## 4. Acceptance Criteria & Verification Checklist

Execute each verification command to confirm end-to-end functionality:

### Check 1: PostgreSQL Readiness & Healthcheck
```bash
docker compose exec db pg_isready -U app_user -d app_db
```
- **Expected Outcome**: `accepting connections`

### Check 2: Django Database Migrations
```bash
docker compose exec backend python manage.py migrate --noinput
```
- **Expected Outcome**: All core Django migrations apply cleanly with zero errors.
- *Notice*: Per [`.agent/rules/ai-guardrails.md`](../.agent/rules/ai-guardrails.md), `makemigrations` is strictly forbidden in automated entrypoints.

### Check 3: Backend Health Probe
```bash
curl -i http://localhost:8080/api/health/
```
- **Expected Outcome**: HTTP `200 OK` with JSON payload:
  ```json
  {"status": "healthy", "service": "backend"}
  ```

### Check 4: Frontend Server-Side Rendering
```bash
curl -i http://localhost:8080/
```
- **Expected Outcome**: HTTP `200 OK` with rendered HTML markup from Next.js SSR.

### Check 5: Internal Docker Network SSR Fetch
Create a test RSC page in `frontend/app/health-check/page.tsx`:
```tsx
import { serverFetch } from '@/lib/api/serverFetch';

export default async function HealthCheckPage() {
  const data = await serverFetch<{ status: string }>('/api/health/');
  return <div>Backend Status: {data.status}</div>;
}
```
Query the route:
```bash
curl -i http://localhost:8080/health-check/
```
- **Expected Outcome**: HTTP `200 OK` with body containing `Backend Status: healthy`. Confirms Node.js SSR successfully routes via internal bridge `INTERNAL_API_BASE_URL` (`http://backend:8000`).

### Check 6: Unprivileged Process Execution (Least Privilege)
```bash
docker compose exec backend whoami
```
- **Expected Outcome**: `appuser` (UID 1001). The container must NEVER run application logic as `root` (UID 0).

### Check 7: Process Signal Handoff (PID 1)
```bash
docker compose exec backend ps -ef
```
- **Expected Outcome**: PID 1 is the Gunicorn or Uvicorn process itself (or entrypoint running `exec "$@"`), guaranteeing prompt propagation of `SIGTERM` and `SIGINT` signals.

---

## 5. Troubleshooting & Remediation

| Issue | Root Cause | Remediation |
| :--- | :--- | :--- |
| `psycopg.OperationalError: could not connect` | PostgreSQL container is still initializing WAL recovery | The `entrypoint.sh` includes a socket readiness loop with retries. Verify database credentials match in `.env`. |
| `CSRF verification failed` on API mutations | Missing CSRF cookie or untrusted origin header | Confirm `CSRF_TRUSTED_ORIGINS` in `config/settings.py` includes `http://localhost:8080` and `http://localhost:3000`. |
| `connect ECONNREFUSED 127.0.0.1:8000` during SSR | Server component fetcher attempting to connect to localhost inside container | Configure `INTERNAL_API_BASE_URL=http://backend:8000` in `.env`. Ensure SSR fetches use `serverFetch.ts`. |
| Permission denied running `entrypoint.sh` | Shell script lacks POSIX execution bit | Execute `chmod +x backend/entrypoint.sh` on the host before building the Docker image. |
