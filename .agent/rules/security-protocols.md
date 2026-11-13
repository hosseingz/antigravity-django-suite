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
  - `CORS_ALLOW_ALL_ORIGINS = False` must be written out literally across all environments except strictly defined, isolated mock unit tests, so relaxing it is immediately visible in review.
  - Development origins (`localhost`, `127.0.0.1`) are environment-gated: inject them into `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, and `ALLOWED_HOSTS` only when `ENVIRONMENT in {"development", "local"}`.
  - Outside development, all three lists must be explicitly configured and non-empty; fail startup closed if missing. Never merge development hostnames (`testserver`, `backend`, `django-app`) into production `ALLOWED_HOSTS`.
  - Subdomain wildcards (`CORS_ALLOWED_ORIGIN_REGEXES`) must only be utilized with strict regex anchors.
- **CSRF & Cookie Protection**:
  - When browser clients interact with cookie-authenticated endpoints, ensure `CORS_ALLOW_CREDENTIALS = True` is paired with explicit origin validation (never wildcard `*`).
  - **Mandatory CSRF Verification for Cookie-CONSUMING Endpoints**: Any state-changing endpoint (POST, PUT, PATCH, DELETE) that **reads, writes, or mints credential cookies** MUST enforce CSRF verification via DRF `CSRFCheck`. This explicitly covers `login/`, `register/`, `token/refresh/`, and `logout/` — not only views reached through `CookieJWTAuthentication`.
    - *Rationale*: DRF's `APIView.as_view()` is marked `csrf_exempt` by design, so standard `CsrfViewMiddleware` never evaluates these endpoints; CSRF is only re-introduced if an authentication class runs `CSRFCheck`. Views declaring `authentication_classes = []` or `permission_classes = [AllowAny]` that read or set `request.COOKIES` are completely exposed unless they invoke `CSRFCheck` explicitly (e.g., via `CookieCSRFProtectedMixin`).
    - *Prohibited*: Relying on `@ensure_csrf_cookie` alone (it mints the cookie and verifies nothing) or relying solely on `SameSite=Lax` without an active check.
    - *Required*: Logout, login, and refresh are CSRF-protected. A CSRF-exempt refresh or logout is a merge blocker (prevents login-CSRF, forced-logout DoS with blacklisting, and cross-origin session rotation).
  - Enforce `CSRF_COOKIE_HTTPONLY = False` so client-side frameworks can read the `csrftoken` cookie for header injection (`X-CSRFToken`), paired with `CSRF_COOKIE_SAMESITE = 'Lax'`.
  - **Cookie Secure Policy is Transport-Derived, Never `DEBUG`-Derived**:
    - Define a single source of truth (`COOKIE_SECURE`) consumed by session, CSRF, and JWT cookie helpers. Computing `secure = not DEBUG` in multiple disparate files is prohibited.
    - Production must fail closed: a non-Secure cookie policy outside `ENVIRONMENT=development|local` is an immediate startup error.
    - Local Docker stacks commonly run `DEBUG=0` over plain HTTP (`http://localhost:8080`). Such stacks MUST set `ENVIRONMENT=development` and `COOKIE_SECURE=0` explicitly. (Symptom of misconfiguration: login returns 200, browser silently discards `Secure` cookies over HTTP, and the next mutation fails with `CSRF Failed: CSRF cookie not set`).
    - `SameSite=Lax` is the default. `SameSite=None` requires `Secure` and a documented cross-site architectural decision.
- **Topology & Deployment Hardening**:
  - **Same-Origin Default Topology**: By default, serve the frontend SPA and `/api/` behind a unified reverse proxy (nginx) host with `NEXT_PUBLIC_API_BASE_URL=""` (relative). Separate subdomains (`app.example.com` -> `api.example.com`) require explicit parent domain configuration (`CSRF_COOKIE_DOMAIN=".example.com"`), because cross-origin JS cannot read an API domain's cookie for double-submit headers.
  - **Auth Endpoint Rate Limiting**: All credential endpoints (`login/`, `register/`, `token/refresh/`, `otp/*`) MUST declare DRF throttle scopes (e.g., `ScopedRateThrottle`).
  - **Deployment Gate**: Production configuration MUST pass `python manage.py check --deploy`, terminate TLS at the edge, and enforce HSTS (`SECURE_HSTS_SECONDS > 0`).
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
- **Fail-Closed Secret Enforcement & Key Diversity**:
  - The framework settings must implement `_require_strong_secret` gating: any placeholder matching the shipped `INSECURE_SECRET_PREFIXES` list (`django-insecure*`, `insecure*`, `change-this*`, `change-me*`, `changeme*`, `replace-*`, `replace_*`, `default-*`) or an empty value MUST resolve to a random key in development and MUST cause an immediate startup crash outside development (`ENVIRONMENT not in {"development", "local"}`).
  - In development environments, empty or placeholder secrets must auto-generate a cryptographically secure random fallback (`secrets.token_urlsafe(64)`), ensuring default development spins up safely without static predictable keys.
  - Startup checks must assert `JWT_SIGNING_KEY != SECRET_KEY` under all runtime environments.

---

## 4. Edge & Reverse Proxy Security (Nginx & Docker)
- **Container Isolation (`no-new-privileges`)**:
  - All production and staging services in `docker-compose.yml` (`backend`, `frontend`) must set `security_opt: ["no-new-privileges:true"]` to prevent unprivileged processes from acquiring escalated root capabilities via `setuid` binaries.
- **Reverse Proxy Header Hardening (Nginx)**:
  - `server_tokens off;` must be configured globally to suppress Nginx version fingerprinting.
  - Set a realistic `client_max_body_size` (e.g., `25M;`) on public ingress to mitigate buffer exhaustion and denial of service.
  - Global baseline response headers must enforce:
    - `X-Content-Type-Options: nosniff`
    - `X-Frame-Options: DENY`
    - `Referrer-Policy: strict-origin-when-cross-origin`
  - Nginx locations that declare their own `add_header` do not inherit server-level headers, so `/static/` and `/media/` must repeat the headers they need.
  - `X-Frame-Options` must match Django's `X_FRAME_OPTIONS` (`DENY`); emitting two different values on one response makes the effective policy depend on browser error handling.
- **User Upload & Media Sandbox Defense**:
  - Any reverse proxy route serving untrusted user media (`/media/`) MUST inject:
    - `Content-Security-Policy: default-src 'none'; sandbox;`
    - `X-Content-Type-Options: nosniff;`
  - This prevents uploaded files (such as malicious HTML, SVG with embedded scripts, or polyglot files) from executing active JavaScript within the origin context.

---

## 5. Domain-Specific Security Protocols (E-Commerce Cart & Guest State)
- **Per-Guest State Isolation**:
  - Anonymous guest shopping sessions MUST never share a static Redis key (such as `"anonymous_session"`), which causes global cart state pollution and privacy leaks between unauthenticated visitors.
  - Every guest visitor must receive an isolated, cryptographically generated UUIDv4 (`cart_guest_uuid`).
  - Frontend client generation of guest UUIDs MUST use CSPRNG (`crypto.getRandomValues`), never predictable pseudo-random generators (`Math.random()`).
  - Backend cart APIs must validate the guest UUID strictly against canonical `uuid.UUID` formatting before interacting with Redis keys to eliminate cache pollution or invalid key injection.
- **Cart Mutation CSRF Defense**:
  - All state-changing cart endpoints (item addition, modification, quantity updates, clearance) accessed via cookie sessions MUST enforce CSRF verification (e.g., via `CartCSRFProtectionMixin`).
  - The guest cart UUID cookie (`cart_guest_uuid`) must be configured with `SameSite=Lax` and transport-derived `secure`.

---

## 6. Authentication Flows, Open Redirect & Credential Redaction
- **Protocol-Relative Open Redirect Defense**:
  - Route guards and login redirects checking the `next` parameter must validate that the destination is strictly internal:
    - Must start with `/` and NOT start with `//` or `/\`.
    - Protocol-relative URLs (e.g., `//evil.com` or `/\evil.com`) are treated by modern browsers as scheme-relative absolute navigations and MUST be rejected, falling back to a fixed internal route (e.g., `/dashboard` in `middleware.ts`).
- **OTP & Sensitive Credential Redaction**:
  - One-Time Passwords (OTP), raw verification codes, and tokens must NEVER be logged to `stdout`, `stderr`, or server logging backends under any log level.
  - Phone numbers received during auth flows must be validated for a plausible digit count (10-15 digits) before triggering notification or cache services; OTP cache keys derive from the digits only, so a digit-less value must be rejected rather than collapsed into one shared key.
- **Throttling Scopes on Auth Handlers**:
  - Endpoints initiating or verifying OTPs (`otp/send/`, `otp/verify/`) MUST define explicit DRF throttle scopes (`throttle_scope = "auth_otp"`, `throttle_scope = "auth_otp_verify"`) with dedicated limits defined in `REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']`.
- **Global Session-Family Revocation**:
  - `CookieJWTAuthentication` must perform an O(1) Redis check against `jwt:user_revoked:{user_id}` on every JWT-authenticated request (header or cookie).
  - Setting this key invalidates every outstanding access token of that user immediately, without waiting for expiration. The shipped `RefreshTokenView` sets it on refresh-token reuse; suspension, password-change and global-logout paths must set the same key.
