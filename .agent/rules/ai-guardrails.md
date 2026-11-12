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
  - **No CSRF Gaps on Cookie-Consuming Auth Endpoints**: CSRF enforcement must not depend on `CookieJWTAuthentication`. Endpoints that mint or consume credentials (`login/`, `register/`, `token/refresh/`, `logout/`) declare `AllowAny` or unauthenticated classes, making DRF's implicit `csrf_exempt` leave them unprotected. They MUST invoke `CSRFCheck` explicitly via `CookieCSRFProtectedMixin`.
  - **Transport-Derived Cookie Security**: `set_auth_cookies` and `clear_auth_cookies` must strictly read a centralized `COOKIE_SECURE` setting, never guessing from `settings.DEBUG`.
- **Rationale**: Storing tokens in `localStorage` leaves credentials vulnerable to XSS theft. Stateless refresh tokens cannot be revoked upon logout or breach. Restricting cookie paths causes premature eviction in frontend route middleware. Sharing `SECRET_KEY` couples JWT validation to core framework signing security. Unprotected login/refresh endpoints enable login-CSRF and cross-origin rotation attacks.
- **Enforcement**:
  - `CookieJWTAuthentication` must verify token `jti` against the Redis blacklist and enforce CSRF checks on mutating requests when authenticated via cookies.
  - `set_auth_cookies` and `clear_auth_cookies` must strictly use `path="/"`, `SameSite="Lax"`, and derive `secure` from `settings.COOKIE_SECURE`.
  - Logout MUST be CSRF-protected, blacklist the presented `jti` in Redis cache for its remaining TTL, and issue explicit Set-Cookie eviction headers.
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

---

## 7. Public/Anonymous Readability vs. the Refresh Signal
- **Rule**: The `token_refresh_required` 401 (anti-silent-degradation) applies only to endpoints that require authentication or to unsafe mutating methods. Public `GET`/`HEAD`/`OPTIONS` endpoints MUST remain readable when the access cookie is absent or expired, even if a refresh cookie is present.
- **Rationale**: In DRF, `authenticate()` executes before permissions are evaluated. Raising an unconditional `AuthenticationFailed` inside `authenticate()` when `raw_token is None` and `has_refresh_cookie is True` turns every public page (e.g., blog post, catalog) into a 401 Unauthorized for any user holding an expired session — an availability bug that degrades user experience.
- **Enforcement**:
  - In `CookieJWTAuthentication`, check `request.parser_context["view"].permission_classes` and `request.method`.
  - For safe methods (`GET`, `HEAD`, `OPTIONS`) on views where permissions do not require authentication (e.g. `AllowAny`), return `None` to allow anonymous reading.
  - For mutating methods (`POST`, `PUT`, `PATCH`, `DELETE`) or protected views (`IsAuthenticated`), raise `AuthenticationFailed` with code `token_refresh_required` to trigger the client-side single-refresh mutex.

---

## 8. API Response & Error Contract (DRF ↔ Client)
- **Rule**: Every API endpoint must conform to an explicit response shape contract, and every 4xx/5xx error must carry a string `detail` and a stable snake_case `code`:
  - **No Success Envelopes**: Success responses are NEVER wrapped in `{data: ...}` envelopes. Single resources return bare objects `{...}`.
  - **Collections Contract**:
    - Pageable collections (`/posts/`) return `{count, next, previous, results}` powered by server-side `PageNumberPagination`. Client-side local slicing (`.slice(0, 9)`) or re-pagination is strictly prohibited; the server owns pagination, filtering (`?category=`), and sorting (`?ordering=`).
    - Bounded lookup collections (`/categories/`, `/tags/`) return bare arrays `[...]` only via documented `pagination_class = None` allowlists.
    - Client code MUST NOT use fallback guessing patterns like `data.results || data || []`.
  - **Consistent Field Naming**: One canonical name per concept across list, detail, and mutation views (e.g. `likes`, `bookmarks`, `comments_count`). Renaming domain fields on the client (e.g. `likes: post.likes_count`) is a contract defect.
  - **Standardized Error Contract**:
    - All non-2xx responses must carry: `{ "detail": "Human-readable message.", "code": "stable_code", "fields"?: { "write_field": ["error"] } }`.
    - `detail` MUST always be a string, never a list. Code must never call `ValidationError({"detail": [...]})`.
    - `fields` is reserved for field validation errors only and must never contain non-field keys (`detail`, `code`, `non_field_errors`).
    - A centralized DRF `EXCEPTION_HANDLER` produces this contract server-side.
  - **Status Code Semantics**:
    - `401 Unauthorized` is reserved exclusively for missing, expired, or invalid credentials to drive the single-refresh mutex.
    - Bad credentials during login are a documented `400 Bad Request` (`code: "invalid_credentials"`), not 401.
  - **Build & Typing Gate**:
    - All client communication modules (`apiConfig.ts`, `apiClient.ts`, `serverFetch.ts`, `errorUtils.ts`, `types/api.ts`) must physically exist and compile cleanly (`npx tsc --noEmit`) before integration is declared complete.
    - No `any` types at API boundaries; interfaces in `types/api.ts` must mirror serializer fields. Union types like `tags: string | string[]` are prohibited.
