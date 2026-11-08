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

---

## 2. CORS & CSRF Hardening
- **Strict Origin Whitelisting**:
  - `CORS_ALLOW_ALL_ORIGINS = False` must be enforced across all environments except strictly defined, isolated mock unit tests.
  - Production and staging must explicitly define `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS` matching configured frontend domains.
  - Subdomain wildcards (`CORS_ALLOWED_ORIGIN_REGEXES`) must only be utilized with strict regex anchors.
- **CSRF & Cookie Protection**:
  - When browser clients interact with cookie-authenticated endpoints, ensure `CORS_ALLOW_CREDENTIALS = True` is paired with explicit origin validation (never wildcard `*`).
  - Enforce `CSRF_COOKIE_HTTPONLY = False` only if client-side frameworks read CSRF tokens from cookies for header submission, or use header-based double-submit patterns with `CSRF_COOKIE_SAMESITE = 'Lax'` / `'Strict'`.
  - For production HTTPS, enforce `SESSION_COOKIE_SECURE = True` and `CSRF_COOKIE_SECURE = True`.

---

## 3. Credential Safety & Secrets Management
- **Zero Secrets in Code or Images**:
  - Secrets (`SECRET_KEY`, database passwords, Stripe/payment credentials, JWT private signing keys) must never be hardcoded, committed to Git, or baked into Docker images.
  - Docker build steps must not leak `.env` or credentials into intermediate cache layers.
- **Environment Configuration**:
  - Use structured, typed environment variables (e.g., `django-environ` or `pydantic-settings`).
  - Provide safe, commented `.env.example` templates with non-functional placeholders.
  - Deny insecure fallbacks for production runtime (e.g., raise an immediate startup exception if `SECRET_KEY` is missing or set to a default development string).
- **Static Analysis & Secret Scanning**:
  - Ensure `.gitignore` explicitly excludes `.env`, `*.pem`, `*.key`, `*.sqlite3`, and sensitive export artifacts.
