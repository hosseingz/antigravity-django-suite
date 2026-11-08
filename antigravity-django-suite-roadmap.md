# Antigravity Django Suite Implementation Roadmap

Comprehensive architectural roadmap and progress tracker for the `antigravity-django-suite` ecosystem.

---

## Suite Architecture & Execution Status

```
[ Phase 1: Foundation & Guardrails ] ─────────► COMPLETED (v1.0.0)
                │
                ▼
[ Phase 2: Docker Infrastructure ] ───────────► COMPLETED (v1.0.0)
                │
                ▼
[ Phase 3: Django Core Architecture ] ────────► COMPLETED (v1.0.0)
                │
                ▼
[ Phase 4: Next.js API Synchronization ] ─────► COMPLETED (v1.0.0)
                │
                ▼
[ Phase 5: Auth & JWT Cookie Sessions ] ──────► READY TO EXECUTE
                │
                ▼
[ Phase 6: Domain E-Commerce Module ] ────────► PLANNED
```

---

## Detailed Phase Breakdown

### Phase 1: Core Foundation & Security Guardrails
- **Status**: Completed
- **Deliverables**:
  - Architectural constraints: `.agent/rules/ai-guardrails.md`
  - Container & CORS/CSRF protocols: `.agent/rules/security-protocols.md`
- **Key Milestones**: Least-privilege containers, non-root execution, zero `makemigrations` in entrypoints, strict relative paths.

---

### Phase 2: Production Docker Infrastructure
- **Status**: Completed
- **Deliverables**:
  - Blueprint: `skills/django-docker-scaffold/SKILL.md`
  - Technical Reference: `skills/django-docker-scaffold/references/security-hardening.md`
  - Resource Templates:
    - `Dockerfile.backend` (multi-stage Python 3.12-slim, non-root `appuser`, cached wheels)
    - `entrypoint.sh` (Python PostgreSQL socket readiness check, migrations, `exec "$@"` PID 1 handoff)
    - `docker-compose.yml` (Nginx, Backend, Frontend, Postgres, Redis, isolated Celery worker/beat profiles)
    - `docker-compose.override.yml`, `.dockerignore`, `.env.example`
- **Key Milestones**: Port isolation, internal bridge segmentation, bounded logging, healthchecks.

---

### Phase 3: Django Core Architecture
- **Status**: Completed
- **Deliverables**:
  - Blueprint: `skills/django-core-architecture/SKILL.md`
  - Technical Reference: `skills/django-core-architecture/references/syspath-resolution.md`
  - Resource Templates:
    - `config/settings.py` (12-factor django-environ, WhiteNoise placement, secure cookies)
    - `manage.py`, `config/wsgi.py`, `config/asgi.py`
    - `config/urls.py` (`/api/health/` container probe)
    - `apps/__init__.py` (dynamic `sys.path` injection)
- **Key Milestones**: `config/` namespace separation, un-prefixed app names, WhiteNoise immediately below SecurityMiddleware.

---

### Phase 4: Next.js API Synchronization Layer
- **Status**: Completed
- **Deliverables**:
  - Blueprint: `skills/nextjs-api-sync/SKILL.md`
  - Technical References:
    - `skills/nextjs-api-sync/references/ssr-vs-csr-routing.md`
    - `skills/nextjs-api-sync/references/error-normalization.md`
  - Resource Templates:
    - `resources/apiConfig.ts`: Dynamic getter evaluation for `getApiBaseUrl()` and `API_ENDPOINTS`
    - `resources/apiClient.ts`: Browser-only Axios instance with single-refresh mutex lock and CSRF injection
    - `resources/serverFetch.ts`: Dedicated RSC fetch utility with automatic Next.js cookie forwarding
    - `resources/errorUtils.ts`: Prioritized DRF error extraction pipeline and form field mapping
- **Key Milestones**:
  - Dual-environment SSR (`INTERNAL_API_BASE_URL`) vs CSR (`NEXT_PUBLIC_API_BASE_URL`) resolution.
  - Strict execution boundary: `apiClient.ts` forbidden in RSC; `serverFetch.ts` enforced for server fetching.
  - Race-condition-free single-refresh mutex lock with loop protection.
  - Normalization of DRF error taxonomy.

---

### Phase 5: Auth & JWT Cookie Sessions (`skills/auth-jwt-cookie-session/`)
- **Status**: Ready to Execute
- **Scope**:
  - DRF + SimpleJWT / dj-rest-auth with secure `HttpOnly` cookie rotation.
  - Zero token storage in browser `localStorage`.
  - Next.js middleware session validation and route protection.

---

### Phase 6: Domain Modules: E-Commerce Cart & Catalog (`skills/domain-ecommerce-cart/`)
- **Status**: Planned
- **Scope**:
  - Modular e-commerce domain app inside `apps/cart/` and `apps/catalog/`.
  - Cart state synchronization across anonymous sessions and authenticated users.
