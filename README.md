# Antigravity Django Suite

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Django: 5.0+](https://img.shields.io/badge/Django-5.0+-green.svg)](https://www.djangoproject.com/)
[![Next.js: 14/15 App Router](https://img.shields.io/badge/Next.js-App%20Router-black.svg)](https://nextjs.org/)
[![Docker: Compose v2](https://img.shields.io/badge/Docker-Compose%20v2-2496ED.svg)](https://www.docker.com/)

An enterprise-grade, high-performance skill suite for **Google Antigravity (AGY)** AI agents and engineering teams. It equips autonomous agents with production-hardened architectural blueprints, reusable code templates, and end-to-end operational runbooks to scaffold, secure, and maintain fullstack **Django REST Framework + Next.js App Router + Docker** platforms without human guidance.

---

## Architectural Highlights

```
                                [ Browser / External Client ]
                                             │
                                             ▼ (Port 8080:80)
                               ┌───────────────────────────┐
                               │    Nginx Reverse Proxy    │
                               └─────────────┬─────────────┘
                                             │
                      ┌──────────────────────┴──────────────────────┐
                      │ Path: /api/, /admin/, /static/, /media/     │ Path: /
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

- **Container Isolation & Least Privilege**:
  - Non-root container execution (`USER appuser`, UID 1001).
  - Explicit PID 1 signal handoff (`exec "$@"`) for graceful shutdown on `SIGTERM`.
  - Zero `makemigrations` in entrypoint scripts to prevent migration drift across replicas.
  - Bounded Docker JSON log rotation (3 files, 10MB limit) preventing disk exhaustion.
  - Port isolation: PostgreSQL, Redis, and internal services only declare `expose:`, unreachable directly from the host.

- **Decoupled Django Architecture**:
  - Project configuration decoupled into `backend/config/` orchestration folder.
  - Dynamic `apps/` syspath injection enabling canonical app registration without prefix pollution (`'users'` instead of `'apps.users'`).
  - 12-factor configuration powered by `django-environ`.
  - Strict WhiteNoise middleware sequencing placed immediately below `SecurityMiddleware`.
  - Dedicated `/api/health/` container liveness probe.

- **Dual-Token HttpOnly Security**:
  - Zero tokens stored in browser `localStorage`, `sessionStorage`, or JavaScript variables (full XSS immunity).
  - Dual cookie management: `pod_access_token` (15 minutes) and `pod_refresh_token` (7 days) scoped explicitly to `Path=/` with `HttpOnly; Secure; SameSite=Lax`.
  - Stateful Refresh Token Rotation (RTR): Single-use refresh tokens tracked in Redis with automatic token family revocation upon reuse detection.
  - Mandatory unique `jti` (JWT ID) claims in all generated payloads for deterministic server-side revocation.
  - Cryptographic separation: dedicated `JWT_SIGNING_KEY` enforced (never reuses Django core `SECRET_KEY`).
  - Custom DRF `CookieJWTAuthentication` with CSRF defense on cookie mutations and anti-silent degradation (explicit 401s).
  - Deterministic logout eviction emitting `Max-Age=0` and past epoch expiration headers.
  - Non-premature route eviction in Next.js Edge middleware allowing page transitions when refresh tokens exist on `Path=/`.
  - Single-refresh mutex lock in Axios preventing race conditions and infinite rotation loops.
  - Redis-backed SMS OTP verification with brute-force lockout rate-limiting and constant-time string comparison (`hmac.compare_digest`).

- **Dual-Environment Networking**:
  - SSR (Server-Side Rendering & Server Actions) resolves to internal Docker bridge via `INTERNAL_API_BASE_URL` (`http://backend:8000`), bypassing egress and TLS overhead.
  - CSR (Client-Side Rendering) resolves to edge proxy via `NEXT_PUBLIC_API_BASE_URL` (`http://localhost:8080`).
  - Strict execution boundary: browser-only Axios client is quarantined from React Server Components.
  - Universal DRF error normalization translating nested validation dictionaries into standardized UI error bags.

- **High-Concurrency Domain Modules**:
  - Redis Hash shopping cart engine delivering sub-millisecond cart mutations decoupled from relational database locks.
  - Transparent anonymous guest tracking via RFC4122 `X-CART-UUID`.
  - Atomic server-side guest-to-user cart merging upon authentication.
  - Monotonic Sequence Guard in Zustand store eliminating UI race conditions during rapid mutation events.

---

## Connecting & Registering in Antigravity

Antigravity automatically discovers customizations by traversing workspace directories and global configuration roots. Customizations load using **progressive disclosure** (injecting names and descriptions into context, then loading full blueprints only when activated):

### Method 1: Automated Full Suite Installation (Recommended)
Deploy the full suite (Roles, Skills, Guardrails, and Workflows) into your application repository with safety tracking and idempotency:

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File .\scripts\install-suite.ps1 -Target "D:\Projects\my-app"

# Preview changes without writing (DryRun)
powershell -ExecutionPolicy Bypass -File .\scripts\install-suite.ps1 -Target "D:\Projects\my-app" -DryRun
```

This installs:
- `.agents/agents/` — Stack-specific roles (`suite-backend-architect`, `suite-qa-release-gate`, etc.)
- `.agents/skills/` — All 5 core skills with blueprints, reference architectures, and code resources
- `.agents/rules/` — Safety protocols and guardrail rules
- `.agents/workflows/` — Structured workflows and phase rosters

### Method 2: Manual / Submodule Setup
To integrate manually into an application repository:

1. Clone or submodule this repository into your project's `.agent/` directory:
   ```bash
   # Option A: Git Submodule (Recommended)
   git submodule add <REPO_URL> .agent/skills/django-suite

   # Option B: Direct Copy
   mkdir -p .agent/skills
   cp -r <PATH_TO_SUITE>/skills/* .agent/skills/
   cp -r <PATH_TO_SUITE>/.agent/rules/* .agent/rules/
   ```

2. Antigravity will automatically index all skills in `.agent/skills/` and guardrail rules in `.agent/rules/`.

### Method 2: Global Customization (Machine-Wide)
To make this suite available to all projects across your development environment:

1. Link or copy the skills into your global Antigravity configuration directory:
   ```bash
   # Linux / macOS
   mkdir -p ~/.gemini/config/skills
   cp -r skills/* ~/.gemini/config/skills/

   # Windows (PowerShell)
   New-Item -ItemType Directory -Force -Path "$HOME\.gemini\config\skills"
   Copy-Item -Recurse skills\* "$HOME\.gemini\config\skills\"
   ```

2. Verify that Antigravity recognizes the installed skills:
   - `django-docker-scaffold`
   - `django-core-architecture`
   - `nextjs-api-sync`
   - `auth-jwt-cookie-session`
   - `domain-ecommerce-cart`

---

## Index of Skills & Technical Blueprints

Each skill includes an authoritative `SKILL.md` blueprint, technical references, and production-tested resource templates:

| Skill | Description | Blueprint Link |
| :--- | :--- | :--- |
| **`django-docker-scaffold`** | Production multi-container Docker Compose, unprivileged non-root Debian Slim images, PID 1 signal handoff, and port isolation. | [`skills/django-docker-scaffold/SKILL.md`](skills/django-docker-scaffold/SKILL.md) |
| **`django-core-architecture`** | Decoupled `config/` namespace, dynamic `apps/` syspath resolution, 12-factor `django-environ`, WhiteNoise, and container health probes. | [`skills/django-core-architecture/SKILL.md`](skills/django-core-architecture/SKILL.md) |
| **`nextjs-api-sync`** | Dual-environment networking (SSR vs CSR), browser Axios single-refresh mutex lock, CSRF injection, and DRF error normalization. | [`skills/nextjs-api-sync/SKILL.md`](skills/nextjs-api-sync/SKILL.md) |
| **`auth-jwt-cookie-session`** | Dual-token HttpOnly cookie authentication (`Path=/`), Redis-backed stateful RTR, dedicated `JWT_SIGNING_KEY`, CSRF defense, and Next.js route guard. | [`skills/auth-jwt-cookie-session/SKILL.md`](skills/auth-jwt-cookie-session/SKILL.md) |
| **`domain-ecommerce-cart`** | Decoupled Redis Hash shopping cart engine, transparent `X-CART-UUID` guest sessions, atomic cart merging, and Zustand monotonic sequence guards. | [`skills/domain-ecommerce-cart/SKILL.md`](skills/domain-ecommerce-cart/SKILL.md) |

---

## Operational Workflows (Autonomous Runbooks)

Step-by-step orchestrator runbooks designed for Antigravity agents to execute fullstack tasks end-to-end without human intervention:

| Runbook | Purpose | Runbook Link |
| :--- | :--- | :--- |
| **Workflow 01: Scaffold Fullstack App** | Autonomous orchestrator for spinning up a fresh Django + Next.js + Docker stack from scratch with complete verification checklists. | [`workflows/01-scaffold-fullstack-app.md`](workflows/01-scaffold-fullstack-app.md) |
| **Workflow 02: Setup Secure Authentication** | Turnkey integration runbook for adding dual-token HttpOnly cookies, DRF auth classes, Next.js middleware, and Zustand auth stores to an active project. | [`workflows/02-setup-secure-auth.md`](workflows/02-setup-secure-auth.md) |
| **Workflow 03: Enable High-Concurrency Cart** | Conditional injection runbook for deploying the Redis shopping cart engine, mounting API endpoints, and linking `X-CART-UUID` headers in the frontend. | [`workflows/03-enable-cart-feature.md`](workflows/03-enable-cart-feature.md) |

---

## AI Guardrails & Security Policies

All skills and workflows adhere strictly to the repository guardrail policies:

- **[AI Guardrails & Architecture Standards](.agent/rules/ai-guardrails.md)**:
  - Enforces `exec "$@"` PID 1 command replacement in shell entrypoints.
  - Mandates socket-level PostgreSQL readiness verification (`pg_isready`).
  - Strictly forbids `makemigrations` inside container entrypoints.
  - Prohibits storing JWTs in web storage; mandates cookie `Path=/`, stateful RTR with Redis blacklist, unique `jti`, dedicated `JWT_SIGNING_KEY`, and CSRF protection on cookie auth.
  - Enforces dual-environment networking (`INTERNAL_API_BASE_URL` vs `NEXT_PUBLIC_API_BASE_URL`).

- **[Security Protocols & Baseline Constraints](.agent/rules/security-protocols.md)**:
  - Mandates unprivileged container user execution (`USER appuser`, UID 1001).
  - Enforces strict CORS origin whitelisting (`CORS_ALLOW_ALL_ORIGINS = False`).
  - Requires credentials pairing (`CORS_ALLOW_CREDENTIALS = True`) with explicit origins.
  - Enforces zero secrets in VCS or Docker cache layers.

---

## Repository Layout

```
antigravity-django-suite/
├── .agent/
│   └── rules/
│       ├── ai-guardrails.md           # Zero-hallucination architectural constraints
│       └── security-protocols.md      # Container, CORS, CSRF, and secret protocols
├── skills/
│   ├── django-docker-scaffold/        # Docker Compose, Dockerfiles, entrypoint
│   ├── django-core-architecture/      # config/ layout, syspath, django-environ
│   ├── nextjs-api-sync/               # SSR/CSR routing, Axios mutex, error normalization
│   ├── auth-jwt-cookie-session/       # Dual HttpOnly tokens, SMS OTP, Next.js middleware
│   └── domain-ecommerce-cart/         # Redis cart, guest UUID, monotonic guard
├── workflows/
│   ├── 01-scaffold-fullstack-app.md   # Runbook: Greenfield fullstack spin-up
│   ├── 02-setup-secure-auth.md        # Runbook: Turnkey HttpOnly auth integration
│   └── 03-enable-cart-feature.md      # Runbook: High-concurrency cart injection
├── antigravity-django-suite-roadmap.md # Master project roadmap & completion tracker
├── LICENSE                            # MIT License
└── README.md                          # Repository documentation & registration guide
```

---

## Project Status & Roadmap

The suite has completed all 9 development phases (v1.1.0). For a comprehensive breakdown of milestones and deliverables, consult the [Implementation Roadmap](antigravity-django-suite-roadmap.md).

---

## License

This project is licensed under the [MIT License](LICENSE).
