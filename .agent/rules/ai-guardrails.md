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
- **Rationale**: TCP port availability does not mean the PostgreSQL engine has completed recovery and is accepting query transactions. Arbitrary `sleep` is fragile and non-deterministic in CI/CD and orchestration.
- **Enforcement**:
  - Use `pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" --timeout=2`.
  - In minimal environments where PostgreSQL client utilities are excluded, use a dedicated Python database connection probe verifying `connection.ensure_connection()`.
  - Impose an explicit timeout limit and retry counter on readiness loops.

---

## 3. Strict Prohibition of `makemigrations` in Container Entrypoints
- **Rule**: Container entrypoints and automated container startup scripts are strictly prohibited from executing `python manage.py makemigrations`.
- **Rationale**: `makemigrations` auto-generates Python migration files in ephemeral container layers. Running this in container startup creates conflicting migration files, uncommitted drift, and non-deterministic schemas across multi-container instances and production environments.
- **Enforcement**:
  - Migrations must be generated explicitly in version control during development.
  - Entrypoints may only run `python manage.py migrate --noinput` to apply existing, committed migration files.

---

## 4. Authentication & JWT Storage Standard
- **Rule**: JSON Web Tokens (Access and Refresh) must NEVER be stored in browser `localStorage`, `sessionStorage`, or JavaScript-accessible memory objects across client-rendered apps.
- **Rationale**: Storing credentials in `localStorage` leaves tokens completely exposed to Cross-Site Scripting (XSS) extraction.
- **Enforcement**:
  - Refresh tokens must be stored exclusively in `HttpOnly`, `Secure`, `SameSite=Lax` (or `Strict`) cookies.
  - Short-lived Access tokens should either be handled via server-mediated session proxies or short-lived in-memory state refreshed via HttpOnly cookie rotation endpoints.
  - Revocation and rotation mechanisms must be enforced server-side.

---

## 5. Dual-Environment Networking for Next.js App Router & Django
- **Rule**: Client-side rendering (CSR) and Server-side rendering (SSR) must use distinct, explicit network bases:
  - `INTERNAL_API_BASE_URL`: Dedicated for server-side fetches (Next.js Node.js runtime to Django container via internal Docker network DNS, e.g., `http://backend:8000`).
  - `NEXT_PUBLIC_API_BASE_URL`: Dedicated for browser client fetches (user browser to exposed public API / reverse proxy host, e.g., `https://api.example.com` or `/api`).
- **Rationale**: Using public domain names inside Docker causes loopback/NAT hairpinning failures or unnecessary egress overhead. Conversely, exposing Docker internal container service names to client browsers breaks client-side requests because `http://backend:8000` cannot be resolved outside the Docker network bridge.
- **Enforcement**:
  - The API sync layer must resolve URLs contextually: inspect execution runtime (Server vs. Client) and choose the appropriate base URL automatically.
  - Disallow hardcoded single base URLs in universal fetch wrappers.
