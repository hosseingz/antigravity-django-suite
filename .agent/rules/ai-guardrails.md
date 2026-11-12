# AI Guardrails & Architecture Standards

These guardrails enforce zero-hallucination, production-ready patterns across all skills and templates in `antigravity-django-suite`. Every AI agent and developer operating within this repository must adhere strictly to these constraints.

---

## 1. Process Execution & Signal Handling in Containers
- **Rule**: All Docker shell entrypoints (`entrypoint.sh`) must terminate with explicit command replacement using `exec "$@"`.
- **Rationale**: Direct execution of background commands or bare commands without `exec` causes the shell (`/bin/sh` or `/bin/bash`) to retain PID 1. This absorbs `SIGTERM` and `SIGINT` signals, preventing graceful container shutdowns and resulting in abrupt `SIGKILL` termination after timeout.
- **Enforcement**:
  - Never run long-running commands as child processes of an entrypoint script without `exec`.
  - Always end container entrypoints with `exec "$@"` to pass PID 1 directly to the target application (e.g., Gunicorn, Uvicorn, Celery).

---

## 2. PostgreSQL Health Checks & Readiness
- **Rule**: Entrypoints and health checks must verify PostgreSQL readiness using dedicated socket checks or `pg_isready`, never arbitrary `sleep` loops or raw TCP port guessing.
- **Clarification**: "Dedicated socket check" means a probe that completes a database handshake (`SELECT 1` over psycopg), not bare `socket.create_connection()`. A successful TCP connect only proves the port listener is bound; PostgreSQL accepts TCP connections before completing WAL recovery and accepting queries, which surfaces as `FATAL: the database system is starting up` during `migrate` on a cold volume. Raw TCP probes are strictly prohibited.
- **Enforcement**:
  - Use `pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" --timeout=2`.
  - In minimal environments where PostgreSQL client utilities are excluded, use a dedicated Python database connection probe executing `SELECT 1` inside the retry loop via psycopg (`connection.ensure_connection()` for Django); never bare `socket.create_connection()`.
  - Impose an explicit timeout limit and retry counter on readiness loops.
  - `depends_on: condition: service_healthy` is not a substitute: it must hold for direct `docker compose up <service>` and restart paths too.

---

## 3. Strict Prohibition of `makemigrations` in Container Entrypoints
- **Rule**: Container entrypoints and automated container startup scripts are strictly prohibited from executing `python manage.py makemigrations`.
- **Rationale**: `makemigrations` auto-generates Python migration files in ephemeral container layers. Running this in container startup creates conflicting migration files, uncommitted drift, and non-deterministic schemas across multi-container instances and production environments.
- **Enforcement**:
  - Migrations must be generated explicitly in version control during development.
  - Entrypoints may only run `python manage.py migrate --noinput` to apply existing, committed migration files.

---

## 4. Single-Flight Container Bootstrap
- **Rule**: Long-running container startup bootstrap steps with shared side effects (`migrate`, `collectstatic`) MUST execute exactly once per stack start — never once per container that reuses the image.
- **Rationale**: An `ENTRYPOINT` is inherited by every service built from that image (`backend`, `celery_worker`, `celery_beat`). Concurrent `migrate` runs race on the migration table, and concurrent `collectstatic` writers can truncate a shared `CompressedManifestStaticFilesStorage` manifest, producing 500s on the first request.
- **Enforcement**:
  - In production orchestration, run `migrate`/`collectstatic` in a single one-shot service (`restart: "no"`); gate consumers with `depends_on: {migrate: {condition: service_completed_successfully}}`.
  - Gate entrypoint bootstrap behind an explicit flag (`RUN_BOOTSTRAP`, default `1`) and set it to `0` for worker/beat services.
  - Celery workers must not mount the static volume.

---

## 5. Authentication, JWT Lifecycle & Cookie Storage Standard
- **Rule**: Authentication across Django REST Framework and client applications (e.g., Next.js App Router) must enforce strict cryptographic isolation, deterministic lifecycle management, and full client-server alignment:
  - **No Web Storage**: JSON Web Tokens (Access and Refresh) must NEVER be stored in browser `localStorage`, `sessionStorage`, or JavaScript-accessible memory objects.
  - **Unified Cookie Scope (`Path=/`)**: The cookie path for BOTH `pod_access_token` and `pod_refresh_token` MUST be explicitly configured to `/`. Restricting the refresh cookie path to specific auth endpoints (e.g., `/api/auth/`) is strictly prohibited, as it breaks Next.js Edge route guards (`middleware.ts`) and SSR session checks.
  - **Mandatory Unique Token Identifiers (`jti`)**: Every generated JWT payload (access and refresh) MUST include a unique cryptographically random `jti` (JWT ID) claim to mitigate replay attacks and enable deterministic server-side revocation.
  - **Stateful Refresh Token Rotation (RTR)**: Refresh tokens must NEVER be purely stateless. Applications must use a persistent data store or fast cache (e.g., Redis or database) to track token lineage, enforce single-use rotation upon refresh, and detect token reuse attacks (which must immediately revoke all tokens in the lineage).
  - **Deterministic Client-Side Eviction**: On logout and session expiration, the server must invalidate the token in the backend cache/blacklist AND instruct the browser to purge cookies by issuing explicit `Set-Cookie` eviction headers with `Max-Age=0` and past expiration (`Expires=Thu, 01 Jan 1970 00:00:00 GMT`) for `Path=/`.
  - **Cryptographic Key Separation**: Signing JWTs using the framework's core `SECRET_KEY` is strictly prohibited. Applications must define and use a dedicated `JWT_SIGNING_KEY` (or asymmetric key pair such as `RS256`/`EdDSA`).
  - **Cookie-Authenticated CSRF Protection**: State-changing requests (POST, PUT, PATCH, DELETE) that authenticate via cookies must enforce robust CSRF countermeasures (e.g., DRF CSRFCheck verification).
- **Rationale**: Storing tokens in `localStorage` leaves credentials vulnerable to XSS theft. Stateless refresh tokens cannot be revoked upon logout or breach. Restricting cookie paths causes premature eviction in frontend route middleware. Sharing `SECRET_KEY` couples JWT validation to core framework signing security.
- **Enforcement**:
  - `CookieJWTAuthentication` must verify token `jti` against the Redis blacklist and enforce CSRF checks on mutating requests when authenticated via cookies.
  - `set_auth_cookies` and `clear_auth_cookies` must strictly use `path="/"`.
  - Refresh endpoints must record old `jti` in Redis blacklist with TTL matching remaining token lifetime and issue new rotated pairs.
  - Startup checks must fail if `JWT_SIGNING_KEY` is missing or identical to `SECRET_KEY`.

---

## 6. Dual-Environment Networking for Next.js App Router & Django
- **Rule**: Client-side rendering (CSR) and Server-side rendering (SSR) must use distinct, explicit network bases:
  - `INTERNAL_API_BASE_URL`: Dedicated for server-side fetches (Next.js Node.js runtime to Django container via internal Docker network DNS, e.g., `http://backend:8000`).
  - `NEXT_PUBLIC_API_BASE_URL`: Dedicated for browser client fetches (user browser to exposed public API / reverse proxy host, e.g., `https://api.example.com` or `/api`).
- **Rationale**: Using public domain names inside Docker causes loopback/NAT hairpinning failures or unnecessary egress overhead. Conversely, exposing Docker internal container service names to client browsers breaks client-side requests because `http://backend:8000` cannot be resolved outside the Docker network bridge.
- **Enforcement**:
  - The API sync layer must resolve URLs contextually: inspect execution runtime (Server vs. Client) and choose the appropriate base URL automatically.
  - Disallow hardcoded single base URLs in universal fetch wrappers.
