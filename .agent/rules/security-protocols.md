# Security Protocols & Baseline Constraints

This document defines mandatory security configurations and runtime controls across Django REST Framework, Next.js, and Docker execution environments.

---

## 1. Unprivileged Container User (`USER appuser`)
- **Principle of Least Privilege**: Never run production application containers as `root` (UID 0).
- **Enforcement**:
  - All Dockerfile templates must provision a dedicated, non-root system group and user (e.g., `groupadd -g 1001 appgroup && useradd -u 1001 -g appgroup -s /bin/sh appuser`).
  - Set ownership on necessary application, media, static, and runtime cache directories (`chown -R appuser:appgroup /app`).
  - Explicitly switch to `USER appuser` prior to defining container `CMD` or executing runtime processes.
  - Development overrides must preserve user IDs to avoid host file permission collisions.
  - **Host Permission Collision Mechanism**: Bind-mounted dev containers must resolve host-container UID mismatch by either (a) building with build args `ARG UID=1000 GID=1000` mapped to user/group creation, or (b) specifying `user: "${UID:-1000}:${GID:-1000}"` in the dev compose override. Running `chown -R` across a bind-mounted source tree is strictly prohibited (as it changes host file ownership and severely slows container boot); restrict container startup ownership adjustments strictly to `static/` and `media/`.

---

## 2. CORS & CSRF Hardening
- **Strict Origin Whitelisting**:
  - `CORS_ALLOW_ALL_ORIGINS = False` must be enforced across all environments except strictly defined, isolated mock unit tests.
  - Production and staging must explicitly define `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS` matching configured frontend domains.
  - Subdomain wildcards (`CORS_ALLOWED_ORIGIN_REGEXES`) must only be utilized with strict regex anchors.
- **CSRF & Cookie Protection**:
  - When browser clients interact with cookie-authenticated endpoints, ensure `CORS_ALLOW_CREDENTIALS = True` is paired with explicit origin validation (never wildcard `*`).
  - **Mandatory CSRF Verification for Cookie Auth**: Any state-changing API request (POST, PUT, PATCH, DELETE) authenticated via cookies (e.g., `CookieJWTAuthentication`) MUST enforce CSRF verification (via DRF CSRFCheck or double-submit CSRF headers). Relying solely on `SameSite=Lax` without active CSRF verification is strictly disallowed.
  - Enforce `CSRF_COOKIE_HTTPONLY = False` only if client-side frameworks read CSRF tokens from cookies for header submission, or use header-based double-submit patterns with `CSRF_COOKIE_SAMESITE = 'Lax'` / `'Strict'`.
  - For production HTTPS, enforce `SESSION_COOKIE_SECURE = True` and `CSRF_COOKIE_SECURE = True`.
- **Cookie Scope Alignment**:
  - All authentication cookies (`pod_access_token` and `pod_refresh_token`) MUST be scoped to `Path=/`. Never scope refresh cookies to subpaths (e.g., `/api/auth/`), as this breaks frontend route guards (`middleware.ts`) and SSR pre-fetching.

---

## 3. Credential Safety & Secrets Management
- **Zero Secrets in Code or Images**:
  - Secrets (`SECRET_KEY`, `JWT_SIGNING_KEY`, database passwords, Stripe/payment credentials, JWT private signing keys) must never be hardcoded, committed to Git, or baked into Docker images.
  - Docker build steps must not leak `.env` or credentials into intermediate cache layers.
- **No Default Insecure Credentials in Orchestration**:
  - Compose interpolation MUST NOT supply a working fallback for secrets. Patterns like `${REDIS_PASSWORD:-redispassword}` in `command:`, `environment:`, or healthcheck probes are prohibited. Use the fail-fast interpolation form `${REDIS_PASSWORD:?REDIS_PASSWORD is required}`.
  - Each secret-bearing URL is defined in exactly one place (`.env`), not duplicated across services. `env_file` supplies credentials to backend processes; client-bundle variables (`NEXT_PUBLIC_*`) are build arguments, never runtime container secrets.
- **Dedicated Cryptographic Signing Keys**:
  - Signing JSON Web Tokens (JWT) using the framework's core `SECRET_KEY` is strictly prohibited. Applications must configure a dedicated, isolated `JWT_SIGNING_KEY` (or asymmetric key pair `RS256`/`EdDSA`).
- **Token Lifecycle & Statefulness**:
  - Every generated JWT must contain a cryptographically unique `jti` (JWT ID) claim.
  - Refresh tokens must never be purely stateless; active tokens, rotations, and blacklists must be managed in a persistent store or fast cache (Redis).
  - Logout and token refresh must execute deterministic eviction: record the `jti` in the server-side blacklist and issue explicit Set-Cookie headers with `Max-Age=0` and past expiration dates on `Path=/`.
- **Environment Configuration**:
  - Use structured, typed environment variables (e.g., `django-environ` or `pydantic-settings`).
  - Provide safe, commented `.env.example` templates with non-functional placeholders.
  - Deny insecure fallbacks for production runtime (e.g., raise an immediate startup exception if `SECRET_KEY` or `JWT_SIGNING_KEY` is missing or set to a default development string).
- **Static Analysis & Secret Scanning**:
  - Ensure `.gitignore` explicitly excludes `.env`, `*.pem`, `*.key`, `*.sqlite3`, and sensitive export artifacts.
